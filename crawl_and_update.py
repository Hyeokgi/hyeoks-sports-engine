import os
import json
import requests
import gspread
from datetime import datetime
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
def fetch_fotmob_league_data(league_id="9116"):
    url = f"https://www.fotmob.com/ko/leagues/{league_id}/overview/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"
    }
    
    print(f" 🌐 실제 웹페이지 접속 시도: {url}")
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        print(f"❌ 웹페이지 접근 실패 (상태 코드: {response.status_code})")
        return None
        
    html_content = response.text
    start_str = '<script id="__NEXT_DATA__" type="application/json">'
    end_str = '</script>'
    
    if start_str in html_content:
        start_idx = html_content.find(start_str) + len(start_str)
        end_idx = html_content.find(end_str, start_idx)
        json_str = html_content[start_idx:end_idx].strip()
        
        try:
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
            print(f"❌ 매립 데이터 JSON 파싱 실패: {e}")
            return None
    return None

# -------------------------------------------------------------------------
# 💡 안전한 날짜 추출 헬퍼 함수
# -------------------------------------------------------------------------
def extract_match_date(match):
    if not isinstance(match, dict):
        return None
    status = match.get('status', {})
    if isinstance(status, dict) and status.get('utcTime'):
        return str(status.get('utcTime')).split('T')[0]
    for field in ['date', 'time', 'timeStr', 'startDate']:
        val = match.get(field)
        if val and isinstance(val, str):
            if 'T' in val: return val.split('T')[0]
            if ' ' in val: return val.split(' ')[0]
            if '-' in val: return val
    return None

# -------------------------------------------------------------------------
# 3. HYEOKS 엔진 연동형 크로노 시뮬레이터 (자체 Elo & Form 추적)
# -------------------------------------------------------------------------
def analyze_matches(data):
    if not data or not isinstance(data, dict):
        return []

    content = data.get('content', data) if isinstance(data, dict) else {}
    fixtures_data = content.get('fixtures', {})
    matches = fixtures_data.get('allMatches', fixtures_data.get('fixtures', []))
    
    if not isinstance(matches, list) or not matches:
        print("⚠️ 경기 목록을 추출하지 못했습니다.")
        return []

    # 1차 패스: 파싱 및 기본 데이터 정제
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

    # 2차 패스: 연대기 순 정렬 (시뮬레이션을 위해 시간순 정렬 필수)
    raw_parsed_matches.sort(key=lambda x: (x['date'], str(x['id'])))

    # 자체 시뮬레이션 엔진 초기화
    elo_dict = {team: 1500.0 for team in unique_teams}
    team_history = {team: [] for team in unique_teams} # 최근 폼 추적용

    processed_rows = []
    
    # 3차 패스: 시간 흐름에 따른 전력 및 폼 연산
    for m in raw_parsed_matches:
        home = m['home']
        away = m['away']
        
        # 경기 시작 직전 시점의 두 팀 체급 확보
        home_elo = elo_dict[home]
        away_elo = elo_dict[away]
        power_diff = round(home_elo - away_elo, 2)
        
        # 최근 5경기 기반의 폼 점수 계산 함수
        def get_form_score(history):
            score = 0.0
            for idx, res in enumerate(history[-5:]):
                weight = 1.0 - (idx * 0.1) # 최근 경기일수록 가중치 부여
                if res == 'W': score += 3.0 * weight
                elif res == 'D': score += 1.0 * weight
            return round(score, 2)
            
        home_form = get_form_score(team_history[home])
        away_form = get_form_score(team_history[away])
        h2h_index = round(home_form - away_form, 2)
        
        # 전술 매칭 아키타입 정의 (체급 차이 기준 분화)
        if power_diff > 80: tactical_match = "주도 vs 역습"
        elif power_diff < -80: tactical_match = "역습 vs 주도"
        else: tactical_match = "균형 vs 균형"
        
        # 경기가 완료되었다면 결과 반영하여 엔진 업데이트 (다음 경기에 영향 제공)
        if m['finished']:
            h_s = m['home_score']
            a_s = m['away_score']
            
            if h_s > a_s:
                h_res, a_res = 'W', 'L'
                S_h, S_a = 1.0, 0.0
            elif h_s < a_s:
                h_res, a_res = 'L', 'W'
                S_h, S_a = 0.0, 1.0
            else:
                h_res, a_res = 'D', 'D'
                S_h, S_a = 0.5, 0.5
                
            team_history[home].append(h_res)
            team_history[away].append(a_res)
            
            # Elo 수학 공식 적용 격차 업데이트
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
            E_a = 1.0 / (1.0 + 10.0 ** ((home_elo - away_elo) / 400.0))
            
            K = 32
            elo_dict[home] += K * (S_h - E_h)
            elo_dict[away] += K * (S_a - E_a)

        # 결과 행 매핑
        processed_rows.append([
            str(m['id']),
            str(m['date']),
            "K리그2",
            home,
            away,
            str(int(m['home_score'])) if m['finished'] else "",
            str(int(m['away_score'])) if m['finished'] else "",
            str(power_diff),
            str(h2h_index),
            tactical_match,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return processed_rows

# -------------------------------------------------------------------------
# 4. 메인 컨트롤러 오케스트레이션
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 시뮬레이션 엔진 가동] ========")
    print("[1/3] 구글 시트 인증 프로세스 진입...")
    sheet = init_google_sheet()
    
    print("[2/3] FotMob 실시간 데이터 파이프라인 타격 중...")
    raw_data = fetch_fotmob_league_data("9116")
    
    if not raw_data:
        print("[오류] 원천 데이터를 확보하지 못해 엔진을 종료합니다.")
        return
        
    print("[3/3] 정성적 전술/상성 데이터 수치화 연산 시작...")
    rows_to_insert = analyze_matches(raw_data)
    
    if rows_to_insert:
        headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈스코어", "원정스코어", "전력차 지표", "상대전적 지표", "전술매칭", "최종 갱신일자"]
        sheet.clear()
        sheet.append_row(headers)
        sheet.append_rows(rows_to_insert)
        print(f" 성공적으로 {len(rows_to_insert)}개의 경기 데이터 및 고도화 변수가 구글 시트에 동기화되었습니다.")
    else:
        print("[경고] 업데이트할 연산 결과가 존재하지 않습니다.")

if __name__ == "__main__":
    main()
