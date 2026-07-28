import os
import json
import requests
import gspread
from datetime import datetime, timedelta
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
# 💡 [HYEOKS 핵심 매트릭스] 유럽 4대 리그 프리시즌 체급 레지스트리
# -------------------------------------------------------------------------
EURO_TIER_REGISTRY = {
    "Arsenal": 1620.0, "Manchester City": 1620.0, "Liverpool": 1620.0, 
    "Manchester United": 1550.0, "Tottenham Hotspur": 1550.0, "Aston Villa": 1550.0, 
    "Newcastle United": 1550.0, "Chelsea": 1550.0, "Brighton & Hove Albion": 1480.0, 
    "Fulham": 1480.0, "Crystal Palace": 1480.0, "Brentford": 1480.0, "Everton": 1460.0, 
    "AFC Bournemouth": 1460.0, "Nottingham Forest": 1410.0, "Wolverhampton Wanderers": 1410.0, 
    "Ipswich Town": 1360.0, "Leicester City": 1360.0, "Southampton": 1350.0, 
    "Coventry City": 1350.0, "Hull City": 1350.0, "Sunderland": 1350.0, "Leeds United": 1360.0,
    "Real Madrid": 1620.0, "Barcelona": 1620.0, "Atletico Madrid": 1550.0, 
    "Real Sociedad": 1550.0, "Athletic Club": 1550.0, "Villarreal": 1530.0, 
    "Real Betis": 1480.0, "Sevilla": 1480.0, "Valencia": 1470.0, "Osasuna": 1470.0, 
    "Getafe": 1460.0, "Celta Vigo": 1460.0, "Rayo Vallecano": 1410.0, "Deportivo Alaves": 1410.0, 
    "Mallorca": 1410.0, "Las Palmas": 1400.0, "Espanyol": 1360.0, "Real Valladolid": 1350.0, 
    "Leganes": 1350.0, "Levante": 1350.0, "Racing Santander": 1350.0, "Deportivo A Coruña": 1350.0, 
    "Elche": 1350.0, "Malaga": 1350.0,
    "Inter": 1620.0, "Juventus": 1620.0, "Milan": 1550.0, "Atalanta": 1550.0, 
    "Roma": 1550.0, "Napoli": 1600.0, "Lazio": 1530.0, "Fiorentina": 1480.0, 
    "Bologna": 1480.0, "Torino": 1470.0, "Monza": 1460.0, "Genoa": 1460.0, 
    "Udinese": 1460.0, "Lecce": 1410.0, "Cagliari": 1410.0, "Empoli": 1400.0, 
    "Verona": 1400.0, "Sassuolo": 1410.0, "Parma": 1360.0, "Como": 1360.0, 
    "Venezia": 1350.0, "Frosinone": 1350.0,
    "Bayern München": 1620.0, "Bayer Leverkusen": 1620.0, "Borussia Dortmund": 1550.0, 
    "RB Leipzig": 1550.0, "Eintracht Frankfurt": 1520.0, "VfB Stuttgart": 1490.0, 
    "Freiburg": 1480.0, "Hoffenheim": 1480.0, "Mainz 05": 1470.0, "Borussia Mönchengladbach": 1460.0, 
    "Werder Bremen": 1460.0, "Augsburg": 1410.0, "Union Berlin": 1410.0, "VfL Wolfsburg": 1420.0, 
    "Borussia Bochum": 1400.0, "St. Pauli": 1360.0, "Holstein Kiel": 1350.0, "Hamburger SV": 1350.0, 
    "Elversberg": 1350.0, "1. FC Köln": 1360.0, "Paderborn": 1350.0, "Schalke 04": 1350.0
}

# -------------------------------------------------------------------------
# 3. FotMob 실시간 데이터 웹페이지 정밀 매립 박스 크롤러
# -------------------------------------------------------------------------
def fetch_fotmob_league_data(league_id, league_name):
    url = f"https://www.fotmob.com/ko/leagues/{league_id}/overview/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"
    }
    
    print(f" 🌐 [{league_name}] 진짜 경기 데이터 블록 탐색 중...")
    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code != 200: return None
            
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
                if isinstance(value, dict):
                    content = value.get('content', {})
                    if isinstance(content, dict) and ('fixtures' in content or 'table' in content or 'matches' in content):
                        return value
                    if 'fixtures' in value or 'table' in value or 'matches' in value:
                        return value
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
# 4. HYEOKS 하이브리드 연대기 시뮬레이터 (경기, 팀, 선수 3대 매트릭스 추출)
# -------------------------------------------------------------------------
def analyze_league_matches(data, league_name):
    if not data: return [], [], []
    
    content = data.get('content', data) if isinstance(data, dict) else {}
    table_data_root = content.get('table', [])
    
    # [A] 팀 통계 데이터 추출 및 가공 구역
    team_stats = {}
    valid_league_teams = set()
    max_pts_in_league = 0
    total_teams_count = 0
    table_rows = []
    
    if isinstance(table_data_root, list) and len(table_data_root) > 0:
        first_item = table_data_root[0]
        if isinstance(first_item, dict):
            t_data = first_item.get('data', {})
            if isinstance(t_data, dict): table_rows = t_data.get('table', [])
            if not table_rows: table_rows = first_item.get('table', [])
    elif isinstance(table_data_root, dict):
        table_rows = table_data_root.get('table', [])
            
    team_summary_rows = []
    if isinstance(table_rows, list):
        table_rows = [r for r in table_rows if isinstance(r, dict)]
        total_teams_count = len(table_rows)
        for row in table_rows:
            t_name = row.get('name')
            if t_name:
                valid_league_teams.add(t_name)
                pts = row.get('pts') or row.get('points', 0)
                try: pts = float(pts)
                except: pts = 0.0
                if pts > max_pts_in_league: max_pts_in_league = pts
                team_stats[t_name] = {
                    'rank': row.get('idx') or row.get('rank', 1),
                    'pts': pts
                }
                # 팀 통계 로우 생성
                team_summary_rows.append([
                    t_name, league_name, str(row.get('idx', '-')), str(int(pts)),
                    str(row.get('played', 0)), f"{row.get('won', 0)}승 {row.get('draw', 0)}무 {row.get('lost', 0)}패",
                    str(row.get('goalsFor', 0)), str(row.get('goalsConceded', 0)), datetime.now().strftime('%Y-%m-%d')
                ])

    # [B] 앱 수준 선수 숨은 전술 지표 추출 구역
    player_rows = []
    p_stats = content.get('stats', {}).get('players', []) if isinstance(content.get('stats'), dict) else []
    if isinstance(p_stats, list):
        for stat_group in p_stats:
            if isinstance(stat_group, dict):
                stat_name = stat_group.get('header', '기타 지표')
                top_players = stat_group.get('topThree', stat_group.get('data', []))
                if isinstance(top_players, list):
                    for p in top_players:
                        if isinstance(p, dict):
                            player_rows.append([
                                str(p.get('id', '-')), p.get('name', 'Unknown'), p.get('teamName', league_name),
                                league_name, stat_name, str(p.get('value', '-')), datetime.now().strftime('%Y-%m-%d')
                            ])

    # [C] 경기 일정 및 인젝터 연산 구역
    matches = []
    if isinstance(data, dict):
        c_node = data.get('content', {})
        search_nodes = [c_node, data] if isinstance(c_node, dict) else [data]
        for node in search_nodes:
            if not isinstance(node, dict): continue
            fix = node.get('fixtures', {})
            if isinstance(fix, dict):
                am = fix.get('allMatches', fix.get('fixtures', []))
                if isinstance(am, list) and len(am) > 0: {matches := am}; break
            elif isinstance(fix, list) and len(fix) > 0: {matches := fix}; break
            mat = node.get('matches', {})
            if isinstance(mat, dict):
                am = mat.get('allMatches', mat.get('matches', []))
                if isinstance(am, list) and len(am) > 0: {matches := am}; break
            elif isinstance(mat, list) and len(mat) > 0: {matches := mat}; break
    elif isinstance(data, list): matches = data

    if not isinstance(matches, list) or not matches: return [], team_summary_rows, player_rows
    matches = [m for m in matches if isinstance(m, dict)]
    
    raw_parsed_matches = []
    today = datetime.now()
    max_future_date = today + timedelta(days=60)
    
    for match in matches:
        status = match.get('status', {}) if isinstance(match.get('status'), dict) else {}
        home_node = match.get('home', {}) if isinstance(match.get('home'), dict) else {}
        away_node = match.get('away', {}) if isinstance(match.get('away'), dict) else {}
        home_team = home_node.get('name')
        away_team = away_node.get('name')
        
        if not home_team or not away_team: continue
        if valid_league_teams and (home_team not in valid_league_teams or away_team not in valid_league_teams): continue
            
        m_date = extract_match_date(match) or datetime.now().strftime('%Y-%m-%d')
        try:
            match_date_obj = datetime.strptime(m_date, '%Y-%m-%d')
            if match_date_obj > max_future_date: continue
        except: pass
            
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
            'id': match.get('id'), 'date': m_date, 'home': home_team, 'away': away_team,
            'finished': is_finished, 'home_score': home_score, 'away_score': away_score
        })

    if not raw_parsed_matches: return [], team_summary_rows, player_rows
    raw_parsed_matches.sort(key=lambda x: (x['date'], str(x['id'])))
    
    finished_count = sum(1 for m in raw_parsed_matches if m['finished'])
    is_preseason = (finished_count == 0)
    all_teams_in_fixtures = set([m['home'] for m in raw_parsed_matches] + [m['away'] for m in raw_parsed_matches])
    
    elo_dict = {}
    for team in all_teams_in_fixtures:
        if team in EURO_TIER_REGISTRY: elo_dict[team] = EURO_TIER_REGISTRY[team]
        elif team in team_stats: elo_dict[team] = 1500.0 + (team_stats[team]['pts'] * 3.0)
        elif is_preseason and team in team_stats:
            rank = team_stats[team]['rank']
            rank_factor = (total_teams_count - rank) / (total_teams_count - 1) if total_teams_count > 1 else 0.5
            elo_dict[team] = 1380.0 + (rank_factor * 240.0)
        else: elo_dict[team] = 1450.0

    team_goals_scored, team_goals_conceded, team_clean_sheets = {}, {}, {}
    for team, initial_elo in elo_dict.items():
        if is_preseason:
            proxy_scored = round((initial_elo - 1200) / 200, 2)
            proxy_conceded = round(max(0.5, 2.5 - proxy_scored), 2)
            proxy_clean = 1 if initial_elo >= 1500 else 0
            team_goals_scored[team] = [proxy_scored] * 5
            team_goals_conceded[team] = [proxy_conceded] * 5
            team_clean_sheets[team] = [proxy_clean] * 5
        else:
            team_goals_scored[team], team_goals_conceded[team], team_clean_sheets[team] = [], [], []

    league_rows = []
    for m in raw_parsed_matches:
        home, away = m['home'], m['away']
        home_elo, away_elo = elo_dict.get(home, 1500.0), elo_dict.get(away, 1500.0)
        power_diff = round(home_elo - away_elo, 2)
        
        def get_recent_avg(history): return round(sum(history[-5:]) / len(history[-5:]), 2) if history else 0.0
        def get_clean_sheet_count(history): return history[-5:].count(1) if history else 0

        attack_trend = round(get_recent_avg(team_goals_scored.get(home)) - get_recent_avg(team_goals_scored.get(away)), 2)
        defense_trend = round(get_recent_avg(team_goals_conceded.get(home)) - get_recent_avg(team_goals_conceded.get(away)), 2)
        sheet_trend = get_clean_sheet_count(team_clean_sheets.get(home)) - get_clean_sheet_count(team_clean_sheets.get(away))
        tactical_match = "주도 vs 역습" if power_diff > 85 else ("역습 vs 주도" if power_diff < -85 else "균형 vs 균형")
        
        if m['finished']:
            h_s, a_s = m['home_score'], m['away_score']
            team_goals_scored.setdefault(home, []).append(h_s); team_goals_scored.setdefault(away, []).append(a_s)
            team_goals_conceded.setdefault(home, []).append(a_s); team_goals_conceded.setdefault(away, []).append(h_s)
            team_clean_sheets.setdefault(home, []).append(1 if a_s == 0 else 0); team_clean_sheets.setdefault(away, []).append(1 if h_s == 0 else 0)
            
            S_h = 1.0 if h_s > a_s else (0.5 if h_s == a_s else 0.0)
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
            K = 40 if league_name in ["챔피언스리그", "유로파리그", "월드컵"] else 32
            elo_dict[home] += K * (S_h - E_h); elo_dict[away] += K * ((1.0 - S_h) - (1.0 - E_h))

        league_rows.append([
            str(m['id']), str(m['date']), league_name, home, away,
            str(int(m['home_score'])) if m['finished'] else "",
            str(int(m['away_score'])) if m['finished'] else "",
            str(power_diff), str(attack_trend), str(defense_trend), str(sheet_trend),
            tactical_match, datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return league_rows, team_summary_rows, player_rows

def update_worksheet_safely(spreadsheet, sheet_title, headers, rows):
    try: worksheet = spreadsheet.worksheet(sheet_title)
    except gspread.WorksheetNotFound: worksheet = spreadsheet.add_worksheet(title=sheet_title, rows="1500", cols="20")
    worksheet.clear()
    worksheet.append_row(headers)
    if rows: worksheet.append_rows(rows)

# -------------------------------------------------------------------------
# 5. 메인 실행 컨트롤러
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 멀티 매트릭스 통합 엔진 v3.5 풀가동] ========")
    TARGET_LEAGUES = {
        "9080": "K리그1", "9116": "K리그2", "47": "EPL", "87": "라리가", 
        "54": "분데스리가", "55": "세리에A", "102": "J1리그"
    }
    sh = init_google_sheet()
    
    match_headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈스코어", "원정스코어", "전력차 지표(Elo)", "공격격차 지표(득점)", "수비격차 지표(실점)", "방어안정성(클린시트)", "전술매칭", "최종 갱신일자"]
    team_headers = ["팀명", "리그", "현재순위", "현재승점", "경기수", "종합전적", "총득점", "총실점", "추적일자"]
    player_headers = ["선수ID", "선수명", "소속팀", "리그", "활약 지표 종류", "기록 수치", "추적일자"]
    
    all_matches, all_teams, all_players = [], [], []
    league_separated_data = {name: [] for name in TARGET_LEAGUES.values()}
    
    for l_id, l_name in TARGET_LEAGUES.items():
        raw_data = fetch_fotmob_league_data(l_id, l_name)
        if raw_data:
            m_rows, t_rows, p_rows = analyze_league_matches(raw_data, l_name)
            if m_rows:
                all_matches.extend(m_rows)
                all_teams.extend(t_rows)
                all_players.extend(p_rows)
                league_separated_data[l_name] = m_rows
                print(f"  -> {l_name} 3대 전술 매트릭스 가공 완주 성공")
        time.sleep(1.0)
        
    if not all_matches:
        print("❌ 동기화할 경기 데이터가 없습니다.")
        return

    print("\n[구글시트] 매트릭스 다각도 탭 매립 동기화 중...")
    all_matches.sort(key=lambda x: (x[1], x[0]), reverse=True)
    update_worksheet_safely(sh, "전체", match_headers, all_matches)
    update_worksheet_safely(sh, "HYEOKS_팀통계", team_headers, all_teams)
    update_worksheet_safely(sh, "HYEOKS_선수통계", player_headers, all_players)
    
    for l_name, rows in league_separated_data.items():
        if rows:
            rows.sort(key=lambda x: (x[1], x[0]))
            update_worksheet_safely(sh, l_name, match_headers, rows)
            
    print(" 🎉 [대성공] 전세계 모든 유럽 프리시즌 지표 복구 및 팀/선수 신규 매트릭스 분리 이식 완료!")

if __name__ == "__main__":
    main()
