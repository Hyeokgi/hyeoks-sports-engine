import os
import json
import requests
import gspread
from datetime import datetime
import time
from oauth2client.service_account import ServiceAccountCredentials

# -------------------------------------------------------------------------
# 1. 구글 시트 API 인증 및 연동 설정
# -------------------------------------------------------------------------
def init_google_sheet():
    secret_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not secret_key:
        raise ValueError("깃허브 Secrets에 GOOGLE_SERVICE_ACCOUNT_KEY가 설정되지 않았습니다.")
    
    credentials_dict = json.loads(secret_key)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scopes)
    gc = gspread.authorize(creds)
    return gc.open("HYEOKS_Sports_Toto_Data").sheet1

# -------------------------------------------------------------------------
# 2. FotMob 실시간 데이터 웹페이지 직공 크롤러
# -------------------------------------------------------------------------
def fetch_fotmob_league_data(league_id, league_name):
    url = f"https://www.fotmob.com/ko/leagues/{league_id}/overview/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"
    }
    
    print(f" 🌐 [{league_name}] 웹페이지 접속 시도...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"  ❌ 접근 실패 (상태 코드: {response.status_code})")
            return None
            
        html_content = response.text
        start_str = '<script id="__NEXT_DATA__" type="application/json">'
        end_str = '</script>'
        
        if start_str in html_content:
            start_idx = html_content.find(start_str) + len(start_str)
            end_idx = html_content.find(end_str, start_idx)
            json_str = html_content[start_idx:end_idx].strip()
            
            full_json = json.loads(json_str)
            page_props = full_json.get('props', {}).get('pageProps', {})
            fallback_data = page_props.get('fallback', {})
            
            for key, value in fallback_data.items():
                if "league" in key and "overview" in key:
                    return value
            if 'data' in page_props:
                return page_props['data']
            return page_props
    except Exception as e:
        print(f"  ❌ 크롤링 중 에러 발생: {e}")
    return None

def extract_match_date(match):
    if not isinstance(match, dict): return None
    status = match.get('status', {})
    if isinstance(status, dict) and status.get('utcTime'):
        return str(status.get('utcTime')).split('T')[0]
    for field in ['date', 'time', 'timeStr']:
        val = match.get(field)
        if val and isinstance(val, str):
            if 'T' in val: return val.split('T')[0]
            if '-' in val: return val
    return None

# -------------------------------------------------------------------------
# 3. HYEOKS 멀티 리그 연대기 시뮬레이터 (공수 스탯 세부 가공 파서)
# -------------------------------------------------------------------------
def analyze_league_matches(data, league_name):
    if not data or not isinstance(data, dict): return []

    content = data.get('content', data) if isinstance(data, dict) else {}
    fixtures_data = content.get('fixtures', {})
    matches = fixtures_data.get('allMatches', fixtures_data.get('fixtures', []))
    
    if not isinstance(matches, list) or not matches:
        return []

    raw_parsed_matches = []
    unique_teams = set()
    
    for match in matches:
        if not isinstance(match, dict): continue
        match_id = match.get('id')
        status = match.get('status', {}) if isinstance(match.get('status'), dict) else {}
        
        home_team = match.get('home', {}).get('name') if isinstance(match.get('home'), dict) else None
        away_team = match.get('away', {}).get('name') if isinstance(match.get('away'), dict) else None
        
        if not home_team or not away_team: continue
        
        unique_teams.add(home_team)
        unique_teams.add(away_team)
        
        m_date = extract_match_date(match) or datetime.now().strftime('%Y-%m-%d')
        is_finished = status.get('finished', False)
        score_str = status.get('scoreStr', '')
        
        home_score, away_score = None, None
        if is_finished and '-' in score_str:
            try:
                parts = score_str.split('-')
                home_score = float(parts[0].strip())
                away_score = float(parts[1].strip())
            except:
                is_finished = False
                
        raw_parsed_matches.append({
            'id': match_id,
            'date': m_date,
            'home': home_team,
            'away': away_team,
            'finished': is_finished,
            'home_score': home_score,
            'away_score': away_score
        })

    # 시간 순서 정렬
    raw_parsed_matches.sort(key=lambda x: (x['date'], str(x['id'])))

    # 리그 전용 시뮬레이션 공간 독립 생성
    elo_dict = {team: 1500.0 for team in unique_teams}
    team_goals_scored = {team: [] for team in unique_teams}   # 최근 득점 트렌드
    team_goals_conceded = {team: [] for team in unique_teams} # 최근 실점 트렌드
    team_clean_sheets = {team: [] for team in unique_teams}    # 클린시트 기록

    league_rows = []
    
    for m in raw_parsed_matches:
        home, away = m['home'], m['away']
        
        # 경기 직전 시점 체급
        home_elo, away_elo = elo_dict[home], elo_dict[away]
        power_diff = round(home_elo - away_elo, 2)
        
        # 최근 5경기 세부 골 패턴 연산 함수
        def get_recent_avg(history):
            if not history: return 0.0
            recent = history[-5:]
            return round(sum(recent) / len(recent), 2)
            
        def get_clean_sheet_count(history):
            if not history: return 0
            return history[-5:].count(1)

        h_avg_scored = get_recent_avg(team_goals_scored[home])
        h_avg_conceded = get_recent_avg(team_goals_conceded[home])
        h_clean_count = get_clean_sheet_count(team_clean_sheets[home])
        
        a_avg_scored = get_recent_avg(team_goals_scored[away])
        a_avg_conceded = get_recent_avg(team_goals_conceded[away])
        a_clean_count = get_clean_sheet_count(team_clean_sheets[away])
        
        # 상대적 스탯 격차 지표로 압축 가공 (홈 - 원정)
        attack_trend = round(h_avg_scored - a_avg_scored, 2)
        defense_trend = round(h_avg_conceded - a_avg_conceded, 2)
        sheet_trend = h_clean_count - a_clean_count
        
        if power_diff > 80: tactical_match = "주도 vs 역습"
        elif power_diff < -80: tactical_match = "역습 vs 주도"
        else: tactical_match = "균형 vs 균형"
        
        # 시뮬레이터 실시간 사후 업데이트
        if m['finished']:
            h_s, a_s = m['home_score'], m['away_score']
            
            # 득실점 패턴 트래킹 아카이브에 적재
            team_goals_scored[home].append(h_s)
            team_goals_scored[away].append(a_s)
            team_goals_conceded[home].append(a_s)
            team_goals_conceded[away].append(h_s)
            
            # 클린시트(무실점) 여부 판정 (1: 무실점 성공, 0: 실점)
            team_clean_sheets[home].append(1 if a_s == 0 else 0)
            team_clean_sheets[away].append(1 if h_s == 0 else 0)
            
            # Elo 연산 변동
            S_h = 1.0 if h_s > a_s else (0.5 if h_s == a_s else 0.0)
            S_a = 1.0 - S_h
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
            E_a = 1.0 - E_h
            
            elo_dict[home] += 32 * (S_h - E_h)
            elo_dict[away] += 32 * (S_a - E_a)

        # 고도화 변수들(최근 공격력 격차, 수비 안정도 격차, 클린시트 격차)을 컬럼에 결합
        league_rows.append([
            str(m['id']),
            str(m['date']),
            league_name,
            home,
            away,
            str(int(m['home_score'])) if m['finished'] else "",
            str(int(m['away_score'])) if m['finished'] else "",
            str(power_diff),
            str(attack_trend),  # 신규 고도화 변수: 최근 공격 트렌드 격차
            str(defense_trend), # 신규 고도화 변수: 최근 수비 불안도 격차
            str(sheet_trend),   # 신규 고도화 변수: 최근 클린시트 안정감 격차
            tactical_match,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return league_rows

# -------------------------------------------------------------------------
# 4. 메인 컨트롤러 오케스트레이션
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 멀티 시뮬레이션 엔진 v2.0 가동] ========")
    
    # 확장 타겟 리그 맵 정의 (FotMob League ID Mapping)
    TARGET_LEAGUES = {
        "55": "K리그1",
        "9116": "K리그2",
        "47": "EPL",
        "87": "라리가",
        "54": "분데스리가"
    }
    
    print("[1/3] 구글 시트 인증 프로세스 진입...")
    sheet = init_google_sheet()
    
    all_combined_rows = []
    
    print("[2/3] 글로벌 다중 리그 실시간 크롤링 및 파이프라인 연산...")
    for l_id, l_name in TARGET_LEAGUES.items():
        raw_data = fetch_fotmob_league_data(l_id, l_name)
        if raw_data:
            league_results = analyze_league_matches(raw_data, l_name)
            all_combined_rows.extend(league_results)
            print(f"  -> {l_name} 연산 완료 ({len(league_results)}개 매치 수치화 완료)")
        else:
            print(f"  -> [경고] {l_name} 데이터를 불러오지 못해 건너뜁니다.")
        time.sleep(1.0) # 글로벌 서버 차단 우회용 안전 대기 시간
        
    print("[3/3] 통합 데이터 구글 시트 동기화 프로세스...")
    if all_combined_rows:
        headers = [
            "경기ID", "일시", "리그", "홈팀", "원정팀", 
            "홈스코어", "원정스코어", "전력차 지표(Elo)", 
            "공격격차 지표(득점)", "수비격차 지표(실점)", "방어안정성(클린시트)", 
            "전술매칭", "최종 갱신일자"
        ]
        sheet.clear()
        sheet.append_row(headers)
        sheet.append_rows(all_combined_rows)
        print(f" 🎉 축하합니다! 총 {len(all_combined_rows)}개의 멀티 리그 매치와 세부 스탯 피처가 구글 시트에 완벽 동기화되었습니다.")
    else:
        print("[오류] 연산된 매치 결과가 하나도 없어 시트를 업데이트하지 못했습니다.")

if __name__ == "__main__":
    main()
