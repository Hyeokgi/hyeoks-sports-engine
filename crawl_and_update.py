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
# 2. FotMob 실시간 데이터 웹페이지 정밀 매립 박스 크롤러
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
        if response.status_code != 200:
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
# 3. HYEOKS 하이브리드 연대기 시뮬레이터 (리스트/딕셔너리 다중 구조 완벽 대응)
# -------------------------------------------------------------------------
def analyze_league_matches(data, league_name):
    if not data: return []
    
    # [방어 패치 1] 순위표(Table) 데이터 다각도 정밀 안전 추출
    team_stats = {}
    valid_league_teams = set()
    max_pts_in_league = 0
    total_teams_count = 0
    table_rows = []
    
    if isinstance(data, dict):
        c_node = data.get('content', {})
        t_node = c_node.get('table', []) if isinstance(c_node, dict) else data.get('table', [])
        
        if isinstance(t_node, list) and len(t_node) > 0:
            first_item = t_node[0]
            if isinstance(first_item, dict):
                t_data = first_item.get('data', {})
                if isinstance(t_data, dict):
                    table_rows = t_data.get('table', [])
                if not table_rows:
                    table_rows = first_item.get('table', [])
        elif isinstance(t_node, dict):
            table_rows = t_node.get('table', [])
            
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
                if pts > max_pts_in_league:
                    max_pts_in_league = pts
                team_stats[t_name] = {
                    'rank': row.get('idx') or row.get('rank', 1),
                    'pts': pts
                }

    # [방어 패치 2] 에러의 주원인이었던 경기 데이터(Matches) 유연한 탐색 엔진 가동
    matches = []
    if isinstance(data, dict):
        c_node = data.get('content', {})
        
        # 탐색 대상 후보 노드들을 순서대로 리스트화
        search_nodes = []
        if isinstance(c_node, dict):
            search_nodes.append(c_node)
        search_nodes.append(data)
        
        for node in search_nodes:
            if not isinstance(node, dict): continue
            
            # 1순위: fixtures 탐색
            fix = node.get('fixtures', {})
            if isinstance(fix, dict):
                am = fix.get('allMatches', fix.get('fixtures', []))
                if isinstance(am, list) and len(am) > 0:
                    matches = am
                    break
            elif isinstance(fix, list) and len(fix) > 0:
                matches = fix
                break
                
            # 2순위: matches 탐색
            mat = node.get('matches', {})
            if isinstance(mat, dict):
                am = mat.get('allMatches', mat.get('matches', []))
                if isinstance(am, list) and len(am) > 0:
                    matches = am
                    break
            elif isinstance(mat, list) and len(mat) > 0:
                matches = mat
                break
    elif isinstance(data, list):
        matches = data

    if not isinstance(matches, list) or not matches:
        return []

    # 안전하게 딕셔너리 형태의 경기 리포트만 필터링
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
        if valid_league_teams and (home_team not in valid_league_teams or away_team not in valid_league_teams):
            continue
            
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

    if not raw_parsed_matches: return []
    raw_parsed_matches.sort(key=lambda x: (x['date'], str(x['id'])))
    
    # Elo 사전 서열 지급 세팅
    elo_dict = {}
    is_preseason = (max_pts_in_league == 0 and total_teams_count > 0)
    
    for team in valid_league_teams:
        if is_preseason:
            rank = team_stats[team]['rank']
            rank_factor = (total_teams_count - rank) / (total_teams_count - 1) if total_teams_count > 1 else 0.5
            elo_dict[team] = 1380.0 + (rank_factor * 240.0)
        else:
            elo_dict[team] = 1500.0 + (team_stats.get(team, {}).get('pts', 0) * 3.0)

    for m in raw_parsed_matches:
        if m['home'] not in elo_dict: elo_dict[m['home']] = 1500.0
        if m['away'] not in elo_dict: elo_dict[m['away']] = 1500.0

    team_goals_scored = {team: [] for team in elo_dict.keys()}
    team_goals_conceded = {team: [] for team in elo_dict.keys()}
    team_clean_sheets = {team: [] for team in elo_dict.keys()}
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
            K = 40 if league_name in ["챔피언스리그", "유로파리그", "월드컵"] else 32
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

def update_worksheet_safely(spreadsheet, sheet_title, headers, rows):
    try:
        worksheet = spreadsheet.worksheet(sheet_title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=sheet_title, rows="1500", cols="20")
    worksheet.clear()
    worksheet.append_row(headers)
    if rows: worksheet.append_rows(rows)

# -------------------------------------------------------------------------
# 4. 메인 실행 컨트롤러
# -------------------------------------------------------------------------
def main():
    print("======== [HYEOKS 글로벌 엔진 v2.90 최종 보수 버전 가동] ========")
    TARGET_LEAGUES = {
        "9080": "K리그1", "9116": "K리그2", "47": "EPL", "87": "라리가", 
        "54": "분데스리가", "55": "세리에A", "102": "J1리그", 
        "42": "챔피언스리그", "73": "유로파리그", "77": "월드컵", "132": "남축INTL"
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
            if league_results:
                all_combined_rows.extend(league_results)
                league_separated_data[l_name] = league_results
                print(f"  -> {l_name} 연산 완료 (데이터 {len(league_results)}건)")
        time.sleep(1.0)
        
    if not all_combined_rows:
        print("❌ 동기화할 경기 데이터가 없습니다.")
        return

    print("\n[구글시트] '전체' 통합 탭 동기화 중...")
    all_combined_rows.sort(key=lambda x: (x[1], x[0]), reverse=True)
    update_worksheet_safely(sh, "전체", headers, all_combined_rows)
    
    print("[구글시트] 각 리그별 개별 탭 분리 동기화 중...")
    for l_name, rows in league_separated_data.items():
        if rows:
            rows.sort(key=lambda x: (x[1], x[0]))
            update_worksheet_safely(sh, l_name, headers, rows)
            
    print(" 🎉 [대성공] 리스트 객체 충돌 에러 완전 해결! 파이프라인 정상 가동 완료!")

if __name__ == "__main__":
    main()
