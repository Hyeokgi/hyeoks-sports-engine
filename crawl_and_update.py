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
# 💡 [HYEOKS 핵심 매트릭스] 지난 시즌 FotMob 실측 베이스라인 (하드코딩 레지스트리 대체)
# -------------------------------------------------------------------------
# 2026-07-28: 유럽 4대 리그 프리시즌 체급을 손으로 채운 EURO_TIER_REGISTRY는
# 승격/강등·시즌 전환마다 수동 갱신이 필요해 계속 낡은 값이 되고, 등록 안 된 팀은
# Elo 격차가 0으로 나오는 원인이었다. fetch_last_season_baseline()이 매 실행마다
# FotMob에서 "지난 시즌 최종 성적"을 직접 스크래핑해 대체한다.
BASELINE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://www.fotmob.com/",
}

# 2026-07-28: 백테스트(유럽 4대리그 6시즌, 실배당 기준)로 검증된 두 가지 보정.
# 데이터에 맞춰 역산한 값이 아니라 ClubElo 등에서 통용되는 축구 홈어드밴티지 경험치를 그대로 채택.
HOME_ADV = 60.0

PLAYER_STAT_CATEGORIES = [
    "goals", "goal_assist", "expected_goals", "expected_assists", "rating",
    "mins_played", "total_scoring_att", "ontarget_scoring_att", "accurate_pass",
    "total_att_assist", "total_tackle", "interception", "clean_sheet", "saves",
]


def _fetch_next_data(url):
    r = requests.get(url, headers=BASELINE_HEADERS, timeout=15)
    if r.status_code != 200:
        return None
    start = '<script id="__NEXT_DATA__" type="application/json">'
    i = r.text.find(start)
    if i == -1:
        return None
    j = r.text.find('</script>', i)
    return json.loads(r.text[i + len(start):j])


def _extract_table_rows(page_props):
    """단일 순위표(dict)와 K리그식 스플릿(composite) 순위표를 모두 처리한다."""
    table_root = page_props.get("table")
    if not isinstance(table_root, list) or not table_root:
        return []
    d0 = table_root[0].get("data", {})
    inner = d0.get("table")
    if isinstance(inner, dict) and inner.get("all"):
        return inner["all"]
    best = None
    for c in d0.get("tables") or []:
        rows = (c.get("table") or {}).get("all") or []
        if best is None or len(rows) > len(best):
            best = rows
    return best or []


def fetch_last_season_baseline(league_id, league_name):
    """지난 시즌 최종 순위표를 FotMob에서 스크래핑해 팀별 시작 Elo/득실/클린시트/선수 스탯을 만든다."""
    base_url = f"https://www.fotmob.com/ko/leagues/{league_id}/overview/"
    try:
        data0 = _fetch_next_data(base_url)
        if not data0:
            return {}, []
        pp0 = data0["props"]["pageProps"]
        seasons = pp0.get("allAvailableSeasons") or []
        if len(seasons) < 2:
            return {}, []
        last_season = seasons[1]

        data1 = _fetch_next_data(f"{base_url}?season={last_season}")
        if not data1:
            return {}, []
        pp1 = data1["props"]["pageProps"]
        rows = _extract_table_rows(pp1)

        stats = pp1.get("stats", {})
        cs_by_id = {}
        for t in stats.get("teams", []):
            if t.get("participant", {}).get("stat", {}).get("name") == "clean_sheet_team":
                try:
                    rcs = requests.get(t["fetchAllUrl"], headers=BASELINE_HEADERS, timeout=15)
                    for e in rcs.json().get("TopLists", [{}])[0].get("StatList", []):
                        cs_by_id[e["TeamId"]] = e.get("StatValue") or 0
                except Exception:
                    pass
                break

        baseline = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            played = row.get("played") or 0
            wins = row.get("wins", row.get("won", 0)) or 0
            draws = row.get("draws", row.get("draw", 0)) or 0
            losses = row.get("losses", row.get("lost", 0)) or 0
            scores = str(row.get("scoresStr") or "0-0").split("-")
            gf = int(scores[0]) if len(scores) == 2 and scores[0].strip().lstrip("-").isdigit() else 0
            ga = int(scores[1]) if len(scores) == 2 and scores[1].strip().lstrip("-").isdigit() else 0
            cs_raw = cs_by_id.get(row.get("id"), 0) or 0
            cs = min(cs_raw, played) if played else cs_raw
            elo = 1500.0 + (wins - losses) * 16 + (gf - ga) * 4 if played else 1500.0
            page_url = row.get("pageUrl") or ""
            baseline[row["name"]] = {
                "id": row.get("id"), "elo": elo, "played": played, "wins": wins, "draws": draws,
                "losses": losses, "gf": gf, "ga": ga, "cs": cs,
                "gf_avg": round(gf / played, 2) if played else 1.3,
                "ga_avg": round(ga / played, 2) if played else 1.3,
                "cs_rate": round(cs / played, 2) if played else 0.25,
                "season": last_season,
                "url": f"https://www.fotmob.com{page_url}" if page_url else base_url,
            }

        id_to_name = {b["id"]: name for name, b in baseline.items() if b.get("id")}
        player_rows = fetch_player_leaderboard(stats, league_name, last_season, id_to_name)
        return baseline, player_rows
    except Exception as e:
        print(f"  ⚠️ [{league_name}] 지난 시즌 베이스라인 수집 실패: {e}")
        return {}, []


def fetch_player_leaderboard(stats, league_name, season, id_to_name):
    """지난 시즌 선수 리더보드(득점/도움/xG/평점 등)를 병합해 선수 DB 행을 만든다."""
    urls = {}
    for p in stats.get("players", []):
        name = p.get("participant", {}).get("stat", {}).get("name")
        if name in PLAYER_STAT_CATEGORIES and p.get("fetchAllUrl"):
            urls[name] = p["fetchAllUrl"]

    by_player = {}
    for cat, url in urls.items():
        try:
            r = requests.get(url, headers=BASELINE_HEADERS, timeout=15)
            entries = r.json().get("TopLists", [{}])[0].get("StatList", [])
        except Exception:
            continue
        for e in entries:
            pid = e.get("ParticiantId")
            if not pid:
                continue
            p = by_player.setdefault(pid, {
                "id": pid, "name": e.get("ParticipantName"), "teamId": e.get("TeamId"),
                "team": e.get("TeamName"), "matches": e.get("MatchesPlayed"),
                "minutes": e.get("MinutesPlayed"),
            })
            p[cat] = e.get("StatValue")
        time.sleep(0.15)

    rows = []
    for pid, p in by_player.items():
        team_name = id_to_name.get(p.get("teamId")) or p.get("team") or ""
        rows.append([
            pid, league_name, team_name, p.get("name"), "", season,
            p.get("matches") or "", "", p.get("minutes") or "",
            p.get("goals") or "", p.get("goal_assist") or "",
            p.get("expected_goals") or "", p.get("expected_assists") or "",
            p.get("total_scoring_att") or "", p.get("ontarget_scoring_att") or "",
            p.get("accurate_pass") or "", p.get("total_att_assist") or "",
            (p.get("total_tackle") or 0) + (p.get("interception") or 0)
            if (p.get("total_tackle") or p.get("interception")) else "",
            p.get("rating") or "", "정상", f"https://www.fotmob.com/players/{pid}",
        ])
    return rows


# -------------------------------------------------------------------------
# 1-1. 상대전적(H2H) 캐시 — 여러 시즌치 과거 맞대결을 미리 모아 h2h_cache.json으로 저장해두고 조회
# (경기당 실시간 스크래핑 대신 정적 캐시를 쓰는 이유: FotMob은 팀 페이지당 요청이 필요해 리그당
#  수십 건이 추가되므로, 주기적으로 갱신하는 캐시 파일로 대체함. scripts/refresh_h2h_cache.py로 재생성)
# -------------------------------------------------------------------------
def load_h2h_cache():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h2h_cache.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _h2h_key(league, home, away):
    return f"{league}|" + "|".join(sorted([home, away]))


def compute_h2h_diff(cache, league, home, away):
    """직전 5회 맞대결에서 현재 홈팀 기준 평균 승점 - 1.0(무승부 기준선). 데이터 없으면 0."""
    entries = cache.get(_h2h_key(league, home, away), [])[-5:]
    if not entries:
        return 0.0
    pts = []
    for e in entries:
        winner_pts = 2 if e["hg"] > e["ag"] else (1 if e["hg"] == e["ag"] else 0)
        pts.append(winner_pts if e["home"] == home else (2 - winner_pts))
    return round((sum(pts) / len(pts)) - 1.0, 2)


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

            # 2026-07-28: FotMob이 fixtures/table을 fallback 캐시가 아니라 pageProps
            # 최상위에 직접 내려주는 구조로 바뀌었다. fallback 안의 "notableMatches"류
            # 위젯(빈 리스트)이 먼저 잡혀 실제 일정을 못 읽는 문제가 있어, 최상위
            # pageProps에 실제 데이터가 있으면 그걸 우선 사용한다.
            top_fixtures = page_props.get('fixtures', {})
            top_all_matches = top_fixtures.get('allMatches', []) if isinstance(top_fixtures, dict) else []
            if (isinstance(top_all_matches, list) and top_all_matches) or page_props.get('table'):
                print(f"   🎉 [{league_name}] 데이터 매칭 성공! (pageProps 직접)")
                return page_props

            fallback_data = page_props.get('fallback', {})

            # 진짜 경기 데이터와 순위표 구조를 들고 있는 노드 추적 필터 (구조 변경 이전 대비 백업 경로)
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
def analyze_league_matches(data, league_name, baseline=None, h2h_cache=None):
    if baseline is None: baseline = {}
    if h2h_cache is None: h2h_cache = {}
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
            # 2026-07-28: FotMob이 순위표 필드명을 won/draw/lost/goalsFor/goalsConceded에서
            # wins/draws/losses/scoresStr("득-실")로 바꿔서, 신구 필드명을 모두 지원한다.
            if not node: return "0", "0.0", "0승 0무 0패", "0.00", "0.00"
            p = float(node.get('played', 0))
            w = float(node.get('won', node.get('wins', 0)) or 0)
            d = float(node.get('draw', node.get('draws', 0)) or 0)
            l = float(node.get('lost', node.get('losses', 0)) or 0)
            if 'goalsFor' in node or 'goalsConceded' in node:
                gf = float(node.get('goalsFor', 0) or 0)
                ga = float(node.get('goalsConceded', 0) or 0)
            else:
                parts = str(node.get('scoresStr') or '0-0').split('-')
                gf = float(parts[0]) if len(parts) == 2 and parts[0].strip().lstrip('-').isdigit() else 0.0
                ga = float(parts[1]) if len(parts) == 2 and parts[1].strip().lstrip('-').isdigit() else 0.0

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
        if team in baseline: elo_dict[team] = baseline[team]['elo']
        elif team in team_map and team_map[team]['all'].get('pts'):
            elo_dict[team] = 1500.0 + (float(team_map[team]['all']['pts']) * 3.0)
        else: elo_dict[team] = 1500.0

    if is_preseason and not any(t in baseline for t in valid_league_teams):
        for team in valid_league_teams:
            rank = team_map.get(team, {}).get('all', {}).get('idx', 10)
            rank_factor = (total_teams_count - rank) / (total_teams_count - 1) if total_teams_count > 1 else 0.5
            elo_dict[team] = 1380.0 + (rank_factor * 240.0)

    team_goals_scored, team_goals_conceded, team_clean_sheets = {}, {}, {}
    for team, initial_elo in elo_dict.items():
        if is_preseason:
            b = baseline.get(team)
            if b:
                proxy_scored, proxy_conceded = b['gf_avg'], b['ga_avg']
                proxy_clean = 1 if b['cs_rate'] >= 0.35 else 0
            else:
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
        h2h_diff = compute_h2h_diff(h2h_cache, league_name, home, away)
        tactical_match = "주도 vs 역습" if power_diff > 85 else ("역습 vs 주도" if power_diff < -85 else "균형 vs 균형")

        if m['finished'] and m['home_score'] != "":
            hs, as_ = float(m['home_score']), float(m['away_score'])
            team_goals_scored.setdefault(home, []).append(hs); team_goals_scored.setdefault(away, []).append(as_)
            team_goals_conceded.setdefault(home, []).append(as_); team_goals_conceded.setdefault(away, []).append(hs)
            team_clean_sheets.setdefault(home, []).append(1 if as_ == 0 else 0); team_clean_sheets.setdefault(away, []).append(1 if hs == 0 else 0)
            key = _h2h_key(league_name, home, away)
            h2h_cache.setdefault(key, []).append({"date": str(m['date']), "home": home, "hg": int(hs), "ag": int(as_)})

            S_h = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
            E_h = 1.0 / (1.0 + 10.0 ** ((away_elo - (home_elo + HOME_ADV)) / 400.0))
            K = 40 if league_name in ["챔피언스리그", "유로파리그"] else 32
            elo_dict[home] += K * (S_h - E_h); elo_dict[away] += K * ((1.0 - S_h) - (1.0 - E_h))

        league_rows.append([
            str(m['id']), str(m['date']), league_name, home, away,
            str(m['home_score']), str(m['away_score']), str(power_diff),
            str(attack_trend), str(defense_trend), str(sheet_trend), str(h2h_diff),
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
# 4. 팀 DB / 선수 DB — HYEOKS_Sports_Toto_Data.xlsx와 동일한 스키마로 작성
# -------------------------------------------------------------------------
TEAM_DB_HEADERS = [
    "키", "리그", "팀", "국가", "기준 시즌", "경기수", "승", "무", "패", "득점", "실점", "클린시트",
    "득점/경기", "실점/경기", "CS율", "수동 Elo", "전술", "최근 5경기 승점", "주전 가용률",
    "FotMob 출처 URL", "사용 Elo", "공격 지수", "수비 지수", "방어 안정성",
]
PLAYER_DB_HEADERS = [
    "선수 ID", "리그", "팀", "선수명", "포지션", "시즌", "출전", "선발", "출전시간", "득점", "도움",
    "xG", "xA", "슈팅", "유효슈팅", "패스 성공률", "키패스", "수비 행동", "평점", "현재 상태", "FotMob URL",
]


def write_team_db(spreadsheet, all_baselines):
    """리그별 지난 시즌 베이스라인으로 팀 DB 탭을 채우고, Elo/공격/수비/방어 지표는 실시간 수식으로 남긴다."""
    rows = []
    for league, baseline in all_baselines.items():
        for team, b in sorted(baseline.items()):
            rows.append([
                f"{league}|{team}", league, team, "", b["season"],
                b["played"], b["wins"], b["draws"], b["losses"], b["gf"], b["ga"], b["cs"],
                "", "", "", "", "", "", "", b["url"], "", "", "", "",
            ])
    try: ws = spreadsheet.worksheet("팀 DB")
    except gspread.WorksheetNotFound: ws = spreadsheet.add_worksheet(title="팀 DB", rows=str(len(rows) + 10), cols="24")
    ws.clear()
    ws.append_row(TEAM_DB_HEADERS)
    if not rows: return
    ws.append_rows(rows, value_input_option="USER_ENTERED")

    n = len(rows) + 1  # 데이터는 2행부터 n행까지
    moef_rows, uvwx_rows = [], []
    for i in range(2, n + 1):
        moef_rows.append([f'=IF(F{i}=0,"",J{i}/F{i})', f'=IF(F{i}=0,"",K{i}/F{i})', f'=IF(F{i}=0,"",L{i}/F{i})'])
        uvwx_rows.append([
            f'=IF(P{i}<>"",P{i},IF(F{i}=0,"",1500+(G{i}-I{i})*16+(J{i}-K{i})*4))',
            f'=IF(M{i}="","",M{i}*100)', f'=IF(N{i}="","",N{i}*100)', f'=O{i}',
        ])
    ws.update(f"M2:O{n}", moef_rows, value_input_option="USER_ENTERED")
    ws.update(f"U2:X{n}", uvwx_rows, value_input_option="USER_ENTERED")


def write_player_db(spreadsheet, all_player_rows):
    try: ws = spreadsheet.worksheet("선수 DB")
    except gspread.WorksheetNotFound: ws = spreadsheet.add_worksheet(title="선수 DB", rows=str(len(all_player_rows) + 10), cols="21")
    ws.clear()
    ws.append_row(PLAYER_DB_HEADERS)
    if all_player_rows:
        ws.append_rows(all_player_rows, value_input_option="USER_ENTERED")

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
    
    match_headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈스코어", "원정스코어", "전력차 지표(Elo)", "공격격차 지표(득점)", "수비격차 지표(실점)", "방어안정성(클린시트)", "상대전적 격차(H2H)", "전술매칭", "최종 갱신일자"]
    h2h_cache = load_h2h_cache()
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
    all_baselines = {}
    all_baseline_player_rows = []

    for l_id, l_name in TARGET_LEAGUES.items():
        baseline, baseline_player_rows = fetch_last_season_baseline(l_id, l_name)
        if baseline:
            all_baselines[l_name] = baseline
            all_baseline_player_rows.extend(baseline_player_rows)
            print(f"  -> {l_name} 지난 시즌 베이스라인 {len(baseline)}개 팀 확보")
        time.sleep(0.5)

        raw_data = fetch_fotmob_league_data(l_id, l_name)
        if raw_data:
            m_rows, t_rows, p_rows = analyze_league_matches(raw_data, l_name, baseline, h2h_cache)
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

    if all_baselines:
        print("\n[구글시트] 팀 DB(지난 시즌 베이스라인) 동기화 중...")
        write_team_db(sh, all_baselines)
    if all_baseline_player_rows:
        print("[구글시트] 선수 DB(지난 시즌 리더보드) 동기화 중...")
        write_player_db(sh, all_baseline_player_rows)

    print(" 🎉 [대성공] HYEOKS 최고존엄 데이터베이스 및 탭 자동 연동 완수!")

if __name__ == "__main__":
    main()
