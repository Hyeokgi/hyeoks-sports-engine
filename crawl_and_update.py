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
    return gc.open("HYEOKS_Sports_Toto_Data")

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
        if response.status_code == 200:
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
                    if "league" in key: return value
                if 'data' in page_props: return page_props['data']
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
# 3. HYEOKS 연대기 시뮬레이터 (공수 지표 가공)
# -------------------------------------------------------------------------
def analyze_league_matches(data, league_name):
    if not data or not isinstance(data, dict): return []
    content = data.get('content', data) if isinstance(data, dict) else {}
    fixtures_data = content.get('fixtures', {})
    matches = fixtures_data.get('allMatches', fixtures_data.get('fixtures', []))
    if not matches and 'matches' in content:
        matches = content.get('matches', {}).get('allMatches', [])
    if not isinstance(matches, list) or not matches: return []

    raw_parsed_matches = []
    unique_teams = set()
    
    for match in matches:
        if not isinstance(match, dict): continue
        match_id = match.get('id')
        status = match.get('status', {}) if isinstance(match.get('status'), dict) else {}
        home_team = match.get('home', {}).get('name')
        away_team = match.get('away', {}).get('name')
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
            except: is_finished = False
                
        raw_parsed_matches.append({
            'id': match_id, 'date': m_date, 'home': home_team, 'away': away_team,
            'finished': is_finished, 'home_score': home_score, 'away_score': away_score
        })

    raw_parsed_matches.sort(key=lambda x: (x['date'], str(x['id'])))
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
            return round(sum(history[-5:]) / len(history[-5:]), 2)
        def get_clean_sheet_count(history):
            if not history: return 0
            return history[-5:].count(1)

        attack_trend = round(get_recent_avg(team_goals_scored[home]) - get_recent_avg(team_goals_scored[away]), 2)
        defense_trend = round(get_recent_avg(team_goals_conceded[home]) - get_recent_avg(team_goals_conceded[away]), 2)
        sheet_trend = get_clean_sheet_count(team_clean_sheets[home]) - get_clean_sheet_count(team_clean_sheets[away])
        tactical_match = "주도 vs 역습" if power_diff > 85 else ("역습 vs 주도" if power_diff < -85 else "균형 vs 균형")
        
        if m['finished']:
            h_s, a_s = m['home_score'], m['away_score']
            team_goals_scored[home].append(h_s)
            team_goals_scored[away].append(a_s)
            team_goals_conceded[home].append(a_s)
            team_goals_conceded[away].append(h_s)
            team_clean_sheets[home].append(1 if a_s == 0 else 0)
            team_clean_sheets[away].append(1 if h_s == 0 else 0)
            
            S_h = 1.0 if h_s > a_s else (0.5 if h_s == a_s else 0.0)
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
            K = 40 if league_name in ["챔피언스리그", "월드컵"] else 32
            elo_dict[home] += K * (S_h - E_h)
            elo_dict[away] += K * ((1.0 - S_h) - (1.0 - E_h))

        league_rows.append([
            str(m['id']), str(m['date']), league_name, home, away,
            str(int(m['home_score'])) if m['finished'] else "",
            str(int(m['away_score'])) if m['finished'] else "",
            str(power_diff), str(attack_trend), str(defense_trend), str(sheet_trend),
            tactical_match, datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return league_rows

# -------------------------------------------------------------------------
# 🛠️ 탭 분할 및 업데이트 제어 함수
# -------------------------------------------------------------------------
def update_worksheet_safely(spreadsheet, sheet_title, headers, rows):
    try:
        worksheet = spreadsheet.worksheet(sheet_title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=sheet_title, rows="1000", cols="20")
    
    worksheet.clear()
    worksheet.append_row(headers)
    if rows:
        worksheet.append_rows(rows)

# -------------------------------------------------------------------------
# 4. 메인 오케스트레이션
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 멀티 리그 구조화 엔진 가동] ========")
    TARGET_LEAGUES = {
        "55": "K리그1", "9116": "K리그2", "47": "EPL", "87": "라리가", 
        "54": "분데스리가", "102": "J1리그", "42": "챔피언스리그", 
        "73": "유로파리그", "77": "월드컵", "132": "남축INTL"
    }
    
    sh = init_google_sheet()
    headers = [
        "경기ID", "일시", "리그", "홈팀", "원정팀", "홈스코어", "원정스코어", 
        "전력차 지표(Elo)", "공격격차 지표(득점)", "수비격차 지표(실점)", 
        "방어안정성(클린시트)", "전술매칭", "최종 갱신일자"
    ]
    
    all_combined_rows = []
    league_separated_data = {name: [] for name in TARGET_LEAGUES.values()}
    
    for l_id, l_name in TARGET_LEAGUES.items():
        raw_data = fetch_fotmob_league_data(l_id, l_name)
        if raw_data:
            league_results = analyze_league_matches(raw_data, l_name)
            all_combined_rows.extend(league_results)
            league_separated_data[l_name] = league_results
            print(f"  -> {l_name} 시뮬레이션 및 분리 완료")
        time.sleep(1.0)
        
    # 1. 전체 탭 가공 (날짜 내림차순 정렬: 최근 날짜가 맨 위로)
    print("\n[업데이트] '전체' 통합 탭 동기화 중 (최신일자 정렬)...")
    all_combined_rows.sort(key=lambda x: (x[1], x[0]), reverse=True)
    update_worksheet_safely(sh, "전체", headers, all_combined_rows)
    
    # 2. 리그별 개별 탭 동기화
    print("[업데이트] 개별 리그 분리 탭 동기화 중...")
    for l_name, rows in league_separated_data.items():
        if rows:
            # 개별 리그는 일정 확인 편의를 위해 시간 순서(오름차순)로 적재
            rows.sort(key=lambda x: (x[1], x[0]))
            update_worksheet_safely(sh, l_name, headers, rows)
            
    print(" 🎉 [대성공] 구글 시트 구조 개편 및 글로벌 데이터 동기화 완료!")

if __name__ == "__main__":
    main()
