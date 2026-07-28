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
# 2. FotMob 실시간 데이터 웹페이지 철벽 필터링 크롤러
# -------------------------------------------------------------------------
def fetch_fotmob_league_data(league_id, league_name):
    url = f"https://www.fotmob.com/ko/leagues/{league_id}/overview/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"
    }
    
    print(f" 🌐 [{league_name}] 데이터 매립 박스 정밀 탐색 중...")
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
            
            # 진짜 경기 데이터와 순위표 구조를 들고 있는 노드 추적 필터
            for key, value in fallback_data.items():
                if isinstance(value, dict):
                    content = value.get('content', {})
                    if isinstance(content, dict) and ('fixtures' in content or 'table' in content or 'matches' in content):
                        print(f"   🎉 [{league_name}] 데이터 매칭 성공!")
                        return value
                    if 'fixtures' in value or 'table' in value or 'matches' in value:
                        print(f"   🎉 [{league_name}] 데이터 매칭 성공!")
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
        if val and isinstance(val, str): return val.split('T')[0] if 'T' in val else val
    return None

# -------------------------------------------------------------------------
# 3. HYEOKS 하이브리드 연대기 시뮬레이터 (경기, 팀, 선수 3대 매트릭스 추출)
# -------------------------------------------------------------------------
def analyze_league_matches(data, league_name):
    if not data: return [], [], []
    
    content = data.get('content', data) if isinstance(data, dict) else {}
    table_data_root = content.get('table', [])
    
    # [A] 구역: 3원 교차 순위표 구조 다각도 분해 및 계산
    tables_dict = {'all': [], 'home': [], 'away': []}
    
    if isinstance(table_data_root, list) and len(table_data_root) > 0:
        for t_item in table_data_root:
            if not isinstance(t_item, dict): continue
            t_data = t_item.get('data', {})
            inner_table = t_data.get('table', {}) if isinstance(t_data, dict) else t_item.get('table', {})
            
            if isinstance(inner_table, dict):
                if 'all' in inner_table: tables_dict['all'] = inner_table.get('all', [])
                if 'home' in inner_table: tables_dict['home'] = inner_table.get('home', [])
                if 'away' in inner_table: tables_dict['away'] = inner_table.get('away', [])
            elif isinstance(inner_table, list):
                ptype = t_item.get('type', 'all')
                if ptype in tables_dict: tables_dict[ptype] = inner_table
                else: tables_dict['all'] = inner_table
    elif isinstance(table_data_root, dict):
        inner_table = table_data_root.get('table', {})
        if isinstance(inner_table, dict):
            tables_dict['all'] = inner_table.get('all', [])
            tables_dict['home'] = inner_table.get('home', [])
            tables_dict['away'] = inner_table.get('away', [])
            
    team_map = {}
    valid_league_teams = set()
    max_pts_in_league = 0
    total_teams_count = 0
    
    for ptype in ['all', 'home', 'away']:
        rows_list = tables_dict[ptype]
        if not isinstance(rows_list, list): continue
        if ptype == 'all': total_teams_count = len(rows_list)
        
        for row in rows_list:
            if not isinstance(row, dict) or not row.get('name'): continue
            t_name = row.get('name')
            valid_league_teams.add(t_name)
            if t_name not in team_map:
                team_map[t_name] = {'all': {}, 'home': {}, 'away': {}}
            team_map[t_name][ptype] = row
            
            if ptype == 'all':
                pts = row.get('pts') or row.get('points', 0)
                try: pts = float(pts)
                except: pts = 0.0
                if pts > max_pts_in_league: max_pts_in_league = pts

    team_summary_rows = []
    for t_name, split_data in team_map.items():
        r_all = split_data.get('all', {})
        r_home = split_data.get('home', {})
        r_away = split_data.get('away', {})
        
        def calculate_metrics(node):
            if not node: return "0", "0.0", "0승 0무 0패", "0.00", "0.00"
            p = float(node.get('played', 0))
            w = float(node.get('won', 0))
            d = float(node.get('draw', 0))
            l = float(node.get('lost', 0))
            gf = float(node.get('goalsFor', 0))
            ga = float(node.get('goalsConceded', 0))
            
            w_rate = round((w / p) * 100, 1) if p > 0 else 0.0
            avg_gf = round(gf / p, 2) if p > 0 else 0.0
            avg_ga = round(ga / p, 2) if p > 0 else 0.0
            return str(int(p)), str(w_rate), f"{int(w)}승 {int(d)}무 {int(l)}패", str(avg_gf), str(avg_ga)
            
        p_all, wr_all, rec_all, gf_all, ga_all = calculate_metrics(r_all)
        p_home, wr_home, rec_home, gf_home, ga_home = calculate_metrics(r_home)
        p_away, wr_away, rec_away, gf_away, ga_away = calculate_metrics(r_away)
        
        form_list = r_all.get('form', [])
        form_str = ",".join([f.get('result', '?') if isinstance(f, dict) else str(f) for f in form_list]) if isinstance(form_list, list) else "-"
        
        team_summary_rows.append([
            t_name, league_name, str(r_all.get('idx', '-')), str(int(r_all.get('pts', 0))),
            p_all, wr_all, rec_all, gf_all, ga_all,
            p_home, wr_home, rec_home, gf_home, ga_home,
            p_away, wr_away, rec_away, gf_away, ga_away,
            form_str, datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])

    # [B] 구역: 선수 세부 스탯 지표 추출
    player_rows = []
    p_stats = content.get('stats', {}).get('players', []) if isinstance(content.get('stats'), dict) else []
    if isinstance(p_stats, list):
        for stat_group in p_stats:
            if isinstance(stat_group, dict):
                stat_name = stat_group.get('header', '기타 스탯')
                top_players = stat_group.get('data', stat_group.get('topThree', []))
                if isinstance(top_players, list):
                    for idx, p in enumerate(top_players):
                        if isinstance(p, dict):
                            p_rank = p.get('rank') or (idx + 1)
                            player_rows.append([
                                str(p.get('id', '-')), p.get('name', 'Unknown'), p.get('teamName', 'Unknown'),
                                league_name, str(p_rank), stat_name, str(p.get('value', '-')), datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            ])

    # [C] 구역: 경기 일정 파싱 및 지표 연산
    matches = []
    if isinstance(data, dict):
        c_node = data.get('content', {})
        search_nodes = [c_node, data] if isinstance(c_node, dict) else [data]
        for node in search_nodes:
            if not isinstance(node, dict): continue
            fix = node.get('fixtures', {})
            if isinstance(fix, dict):
                am = fix.get('allMatches', fix.get('fixtures', []))
                if isinstance(am, list) and len(am) > 0:
                    matches = am
                    break
            elif isinstance(fix, list) and len(fix) > 0:
                matches = fix
                break
            mat = node.get('matches', {})
            if isinstance(mat, dict):
                am = mat.get('allMatches', mat.get('matches', []))
                if isinstance(am, list) and len(am) > 0:
                    matches = am
                    break
            elif isinstance(mat, list) and len(mat) > 0:
                matches = mat
                break
    elif isinstance(data, list): matches = data

    if not isinstance(matches, list) or not matches: 
        return [], team_summary_rows, player_rows
        
    matches = [m for m in matches if isinstance(m, dict)]
    raw_parsed_matches = []
    max_future_date = datetime.now() + timedelta(days=60)
    
    for match in matches:
        home_node = match.get('home', {}) if isinstance(match.get('home'), dict) else {}
        away_node = match.get('away', {}) if isinstance(match.get('away'), dict) else {}
        home_team = home_node.get('name')
        away_team = away_node.get('name')
        
        if not home_team or not away_team: continue
        if valid_league_teams and (home_team not in valid_league_teams or away_team not in valid_league_teams): continue
            
        m_date = extract_match_date(match) or datetime.now().strftime('%Y-%m-%d')
        try:
            if datetime.strptime(m_date, '%Y-%m-%d') > max_future_date: continue
        except: pass
            
        status = match.get('status', {}) if isinstance(match.get('status'), dict) else {}
        is_finished = status.get('finished', False)
        score_str = status.get('scoreStr', '')
        
        home_score, away_score = "", ""
        if is_finished and '-' in score_str:
            parts = score_str.split('-')
            if len(parts) == 2:
                home_score, away_score = parts[0].strip(), parts[1].strip()
            
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
        elif team in team_map and team_map[team]['all'].get('pts'):
            elo_dict[team] = 1500.0 + (float(team_map[team]['all']['pts']) * 3.0)
        else: elo_dict[team] = 1500.0

    if is_preseason and not any(t in EURO_TIER_REGISTRY for t in valid_league_teams):
        for team in valid_league_teams:
            rank = team_map.get(team, {}).get('all', {}).get('idx', 10)
            rank_factor = (total_teams_count - rank) / (total_teams_count - 1) if total_teams_count > 1 else 0.5
            elo_dict[team] = 1380.0 + (rank_factor * 240.0)

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

        # [오타 수정 완료] 하단 시트 매핑 변수명 일치
        attack_trend = round(get_recent_avg(team_goals_scored.get(home)) - get_recent_avg(team_goals_scored.get(away)), 2)
        defense_trend = round(get_recent_avg(team_goals_conceded.get(home)) - get_recent_avg(team_goals_conceded.get(away)), 2)
        sheet_trend = get_clean_sheet_count(team_clean_sheets.get(home)) - get_clean_sheet_count(team_clean_sheets.get(away))
        tactical_match = "주도 vs 역습" if power_diff > 85 else ("역습 vs 주도" if power_diff < -85 else "균형 vs 균형")
        
        if m['finished'] and m['home_score'] != "":
            hs, as_ = float(m['home_score']), float(m['away_score'])
            team_goals_scored.setdefault(home, []).append(hs); team_goals_scored.setdefault(away, []).append(as_)
            team_goals_conceded.setdefault(home, []).append(as_); team_goals_conceded.setdefault(away, []).append(hs)
            team_clean_sheets.setdefault(home, []).append(1 if as_ == 0 else 0); team_clean_sheets.setdefault(away, []).append(1 if hs == 0 else 0)
            
            S_h = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
            K = 40 if league_name in ["챔피언스리그", "유로파리그"] else 32
            elo_dict[home] += K * (S_h - E_h); elo_dict[away] += K * ((1.0 - S_h) - (1.0 - E_h))

        league_rows.append([
            str(m['id']), str(m['date']), league_name, home, away,
            str(m['home_score']), str(m['away_score']), str(power_diff),
            str(attack_trend), str(defense_trend), str(sheet_trend), 
            tactical_match, datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
    return league_rows, team_summary_rows, player_rows

def update_worksheet_safely(spreadsheet, sheet_title, headers, rows):
    try: worksheet = spreadsheet.worksheet(sheet_title)
    except gspread.WorksheetNotFound: worksheet = spreadsheet.add_worksheet(title=sheet_title, rows="2000", cols="25")
    worksheet.clear()
    worksheet.append_row(headers)
    if rows: worksheet.append_rows(rows)

# -------------------------------------------------------------------------
# 5. 메인 컨트롤 오케스트레이션
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 멀티 매트릭스 통합 엔진 v4.5 Pro 가동] ========")
    TARGET_LEAGUES = {
        "9080": "K리그1", "9116": "K리그2", "47": "EPL", "87": "라리가", 
        "54": "분데스리가", "55": "세리에A", "102": "J1리그"
    }
    sh = init_google_sheet()
    
    match_headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈스코어", "원정스코어", "전력차 지표(Elo)", "공격격차 지표(득점)", "수비격차 지표(실점)", "방어안정성(클린시트)", "전술매칭", "최종 갱신일자"]
    team_headers = [
        "팀명", "리그", "현재순위", "현재승점", 
        "종합_경기수", "종합_승률(%)", "종합_전적", "종합_평균득점", "종합_평균실점",
        "홈_경기수", "홈_승률(%)", "홈_전적", "홈_평균득점", "홈_평균실점",
        "원정_경기수", "원정_승률(%)", "원정_전적", "원정_평균득점", "원정_평균실점",
        "최근5경기_폼", "최종갱신일자"
    ]
    player_headers = ["선수ID", "선수명", "소속팀", "리그", "지표순위", "활약 지표 종류", "기록 수치", "최종갱신일자"]
    
    all_matches, all_teams, all_players = [], [], []
    league_separated_data = {name: [] for name in TARGET_LEAGUES.values()}
    
    for l_id, l_name in TARGET_LEAGUES.items():
        raw_data = fetch_fotmob_league_data(l_id, l_name)
        if raw_data:
            m_rows, t_rows, p_rows = analyze_league_matches(raw_data, l_name)
            # 조건 방어 해제: 팀 통계나 선수 통계가 확보되었다면 파이프라인 무조건 가동
            if m_rows or t_rows or p_rows:
                all_matches.extend(m_rows)
                all_teams.extend(t_rows)
                all_players.extend(p_rows)
                league_separated_data[l_name] = m_rows
                print(f"  -> {l_name} 3대 매트릭스 전술 분석 완료")
        time.sleep(1.0)
        
    if not all_matches and not all_teams:
        print("❌ 동기화할 데이터가 존재하지 않습니다.")
        return

    print("\n[구글시트] 매트릭스 다각도 탭 매립 동기화 중...")
    if all_matches:
        all_matches.sort(key=lambda x: (x[1], x[0]), reverse=True)
        update_worksheet_safely(sh, "전체", match_headers, all_matches)
        
    update_worksheet_safely(sh, "HYEOKS_팀통계", team_headers, all_teams)
    update_worksheet_safely(sh, "HYEOKS_선수통계", player_headers, all_players)
    
    for l_name, rows in league_separated_data.items():
        if rows:
            rows.sort(key=lambda x: (x[1], x[0]))
            update_worksheet_safely(sh, l_name, match_headers, rows)
            
    print(" 🎉 [대성공] HYEOKS 최고존엄 데이터베이스 및 탭 자동 연동 완수!")

if __name__ == "__main__":
    main()
