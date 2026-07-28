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
    
    print(f" 🌐 [{league_name}] 데이터 매립 박스 탐색 중...")
    try:
        response = requests.get(url, headers=headers, timeout=12)
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
                if "league" in key:
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
# 3. HYEOKS 하이브리드 연대기 시뮬레이터 (컵대회/국가대항전 완전 방어)
# -------------------------------------------------------------------------
def analyze_league_matches(data, league_name):
    if not data or not isinstance(data, dict): return []

    content = data.get('content', data) if isinstance(data, dict) else {}
    fixtures_data = content.get('fixtures', {})
    matches = fixtures_data.get('allMatches', fixtures_data.get('fixtures', []))
    
    # 토너먼트/컵대회 구조(최근 경기와 예정 경기가 분리된 경우) 방어 코드
    if not matches and 'matches' in content:
        matches = content.get('matches', {}).get('allMatches', [])
        
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

    # 연대기 순 정렬
    raw_parsed_matches.sort(key=lambda x: (x['date'], str(x['id'])))

    # 독립 스탯 연산 보드 빌드
    elo_dict = {team: 1500.0 for team in unique_teams}
    team_goals_scored = {team: [] for team in unique_teams}
    team_goals_conceded = {team: [] for team in unique_teams}
    team_clean_sheets = {team: [] for team in unique_teams}

    league_rows = []
    
    for m in raw_parsed_matches:
        home, away = m['home'], m['away']
        
        home_elo, away_elo = elo_dict[home], elo_dict[away]
        power_diff = round(home_elo - away_elo, 2)
        
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
        
        attack_trend = round(h_avg_scored - a_avg_scored, 2)
        defense_trend = round(h_avg_conceded - a_avg_conceded, 2)
        sheet_trend = h_clean_count - a_clean_count
        
        if power_diff > 85: tactical_match = "주도 vs 역습"
        elif power_diff < -85: tactical_match = "역습 vs 주도"
        else: tactical_match = "균형 vs 균형"
        
        if m['finished']:
            h_s, a_s = m['home_score'], m['away_score']
            
            team_goals_scored[home].append(h_s)
            team_goals_scored[away].append(a_s)
            team_goals_conceded[home].append(a_s)
            team_goals_conceded[away].append(h_s)
            
            team_clean_sheets[home].append(1 if a_s == 0 else 0)
            team_clean_sheets[away].append(1 if h_s == 0 else 0)
            
            S_h = 1.0 if h_s > a_s else (0.5 if h_s == a_s else 0.0)
            S_a = 1.0 - S_h
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
            E_a = 1.0 - E_h
            
            # 컵대회/월드컵 토너먼트의 경우 매치 중요도를 감안하여 K-factor 상향 조정 적용 가능
            K = 40 if league_name in ["챔피언스리그", "월드컵"] else 32
            elo_dict[home] += K * (S_h - E_h)
            elo_dict[away] += K * (S_a - E_a)

        league_rows.append([
            str(m['id']),
            str(m['date']),
            league_name,
            home,
            away,
            str(int(m['home_score'])) if m['finished'] else "",
            str(int(m['away_score'])) if m['finished'] else "",
            str(power_diff),
            str(attack_trend),
            str(defense_trend),
            str(sheet_trend),
            tactical_match,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return league_rows

# -------------------------------------------------------------------------
# 4. 메인 컨트롤러 오케스트레이션
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 글로벌 시뮬레이션 엔진 v2.5 가동] ========")
    
    # 확장된 전체 타겟 리그 및 대형 토너먼트 매핑
    TARGET_LEAGUES = {
        "55": "K리그1",
        "9116": "K리그2",
        "47": "EPL",
        "87": "라리가",
        "54": "분데스리가",
        "102": "J1리그",
        "42": "챔피언스리그",
        "73": "유로파리그",
        "77": "월드컵",
        "132": "남축INTL"
    }
    
    print("[1/3] 구글 시트 인증 프로세스 진입...")
    sheet = init_google_sheet()
    
    all_combined_rows = []
    
    print("[2/3] 전세계 10대 리그/대회 실시간 동시 시뮬레이션 전개...")
    for l_id, l_name in TARGET_LEAGUES.items():
        raw_data = fetch_fotmob_league_data(l_id, l_name)
        if raw_data:
            league_results = analyze_league_matches(raw_data, l_name)
            all_combined_rows.extend(league_results)
            print(f"  -> {l_name} 연산 완료 ({len(league_results)}개 매치 계측 완료)")
        else:
            print(f"  -> [경고] {l_name}의 특수 토너먼트 데이터 레이어를 찾지 못해 스킵합니다.")
        time.sleep(1.2) # 글로벌 방화벽 차단 회피용 딜레이
        
    print("[3/3] 글로벌 대통합 데이터 구글 시트 사사 동기화...")
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
        print(f" 🎉 [대성공] 총 {len(all_combined_rows)}개의 글로벌 매치 고도화 피처가 구글 시트에 이식되었습니다.")
    else:
        print("[오류] 연산 완료된 경기 매트릭스가 존재하지 않습니다.")

if __name__ == "__main__":
    main()
