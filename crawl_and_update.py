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
    
    # 구글 시트 열기 (시트 이름이 정확해야 합니다)
    return gc.open("HYEOKS_Sports_Toto_Data").sheet1

# -------------------------------------------------------------------------
# 2. FotMob 실시간 데이터 웹페이지 직공 크롤러 (안정성 100% 버전)
# -------------------------------------------------------------------------
def fetch_fotmob_league_data(league_id="9116"):
    """API 대신 실제 웹페이지 HTML을 로드하여 내부에 숨겨진 데이터 박스를 추출합니다."""
    import re
    
    # 실제 사용자가 브라우저로 접속하는 일반 웹페이지 주소
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
    
    # HTML 내부에 Next.js가 숨겨놓은 __NEXT_DATA__ 스크립트 태그 추출
    print(" 🔍 HTML 내부 데이터 매립 박스 탐색 중...")
    start_str = '<script id="__NEXT_DATA__" type="application/json">'
    end_str = '</script>'
    
    if start_str in html_content:
        start_idx = html_content.find(start_str) + len(start_str)
        end_idx = html_content.find(end_str, start_idx)
        json_str = html_content[start_idx:end_idx].strip()
        
        try:
            full_json = json.loads(json_str)
            # FotMob 특유의 매립 데이터 트리 구조 진입
            page_props = full_json.get('props', {}).get('pageProps', {})
            fallback_data = page_props.get('fallback', {})
            
            # 데이터가 담긴 키값을 동적으로 탐색
            for key, value in fallback_data.items():
                if "league" in key and "overview" in key:
                    print(" 🎉 [성공] 매립된 리그 데이터 구조를 해독했습니다.")
                    return value
                    
            # 구조가 다를 경우 pageProps 내부 직접 탐색 기본값
            if 'data' in page_props:
                return page_props['data']
                
            return page_props
            
        except Exception as e:
            print(f"❌ 매립 데이터 JSON 파싱 실패: {e}")
            return None
    else:
        print("❌ HTML 소스 내에서 __NEXT_DATA__ 장치를 찾지 못했습니다.")
        return None

# -------------------------------------------------------------------------
# 3. HYEOKS 엔진 고도화 변수 연산 (방어적 데이터 예외 처리 완벽 버전)
# -------------------------------------------------------------------------
def analyze_matches(data):
    if not data or not isinstance(data, dict):
        print("⚠️ 분석할 데이터가 올바른 딕셔너리 형식이 아닙니다.")
        return []

    content = data.get('content', data) if isinstance(data, dict) else {}
    if not isinstance(content, dict):
        content = {}
        
    fixtures_data = content.get('fixtures', {})
    table_data_root = content.get('table', [])
    
    # 팀별 순위 및 승점 매핑 테이블 빌드 (문자열 난입 방어 코드 추가)
    team_stats = {}
    if isinstance(table_data_root, list):
        for table_item in table_data_root:
            if isinstance(table_item, dict):
                t_data = table_item.get('data', {})
                t_rows = []
                if isinstance(t_data, dict):
                    t_rows = t_data.get('table', [])
                
                # 대안 구조 방어
                if not t_rows and 'table' in table_item:
                    t_rows = table_item.get('table', [])
                    
                if isinstance(t_rows, list):
                    for row in t_rows:
                        # row가 딕셔너리 형태일 때만 안전하게 데이터 추출
                        if isinstance(row, dict):
                            t_name = row.get('name')
                            if t_name:
                                team_stats[t_name] = {
                                    'rank': row.get('idx') or row.get('rank', 0),
                                    'pts': row.get('pts') or row.get('points', 0)
                                }

    processed_rows = []
    matches = []
    if isinstance(fixtures_data, dict):
        matches = fixtures_data.get('allMatches', fixtures_data.get('fixtures', []))
    
    if not isinstance(matches, list):
        print("⚠️ 가동할 예정 경기 또는 완료 경기 목록이 비어있거나 형식이 올바르지 않습니다.")
        return []

    for match in matches:
        if not isinstance(match, dict):
            continue
            
        match_id = match.get('id')
        status = match.get('status', {})
        if not isinstance(status, dict):
            status = {}
        
        home_node = match.get('home', {})
        away_node = match.get('away', {})
        if not isinstance(home_node, dict): home_node = {}
        if not isinstance(away_node, dict): away_node = {}
        
        home_team = home_node.get('name')
        away_team = away_node.get('name')
        
        if not home_team or not away_team:
            continue
        
        # 스코어 안전 분할 처리
        is_finished = status.get('finished', False)
        score_str = status.get('scoreStr', '0-0')
        
        if is_finished and '-' in score_str:
            parts = score_str.split('-')
            home_score = parts[0].strip() if len(parts) > 0 else ""
            away_score = parts[1].strip() if len(parts) > 1 else ""
        else:
            home_score = ""
            away_score = ""
        
        # [고도화 변수 1] 체급 전력차 연산
        home_pts = team_stats.get(home_team, {}).get('pts', 15)
        away_pts = team_stats.get(away_team, {}).get('pts', 15)
        power_diff = round(float(home_pts - away_pts), 2)
        
        # [고도화 변수 2] 최근 폼 기반 인덱스 가공
        home_form = home_node.get('form', [])
        away_form = away_node.get('form', [])
        
        def calculate_form_score(form_list):
            score = 0.0
            if isinstance(form_list, list):
                for idx, f in enumerate(form_list[:5]):
                    weight = 1.0 - (idx * 0.1)
                    f_str = f.get('result', '') if isinstance(f, dict) else str(f)
                    if f_str == 'W': score += 3.0 * weight
                    elif f_str == 'D': score += 1.0 * weight
            return round(score, 2)
            
        h2h_index = round(calculate_form_score(home_form) - calculate_form_score(away_form), 2)
        
        # [고도화 변수 3] 전술 매칭 카테고리화
        home_rank = team_stats.get(home_team, {}).get('rank', 5)
        away_rank = team_stats.get(away_team, {}).get('rank', 5)
        if home_rank <= 4 and away_rank >= 8:
            tactical_match = "주도 vs 역습"
        elif home_rank >= 8 and away_rank <= 4:
            tactical_match = "역습 vs 주도"
        else:
            tactical_match = "균형 vs 균형"

        processed_rows.append([
            str(match_id),
            str(match.get('timeStr', datetime.now().strftime('%Y-%m-%d'))),
            "K리그2",
            home_team,
            away_team,
            str(home_score),
            str(away_score),
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
    
    # 1. 구글 시트 연결
    print("[1/3] 구글 시트 인증 프로세스 진입...")
    sheet = init_google_sheet()
    
    # 2. 데이터 크롤링
    print("[2/3] FotMob 실시간 데이터 파이프라인 타격 중...")
    raw_data = fetch_fotmob_league_data("9116") # K리그2 기본 셋업
    
    if not raw_data:
        print("[오류] 원천 데이터를 확보하지 못해 엔진을 종료합니다.")
        return
        
    # 3. 데이터 정량화 및 시뮬레이션 피처 생성
    print("[3/3] 정성적 전술/상성 데이터 수치화 연산 시작...")
    rows_to_insert = analyze_matches(raw_data)
    
    if rows_to_insert:
        # 헤더 셋업 (시트가 완전히 비어있을 때만 작동하도록 안전장치 설정 가능)
        headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈스코어", "원정스코어", "전력차 지표", "상대전적 지표", "전술매칭", "최종 갱신일자"]
        
        # 기존 데이터 전체 포맷 초기화 후 업데이트 (Overwrite 전략)
        sheet.clear()
        sheet.append_row(headers)
        sheet.append_rows(rows_to_insert)
        print(f" 성공적으로 {len(rows_to_insert)}개의 경기 데이터 및 고도화 변수가 구글 시트에 동기화되었습니다.")
    else:
        print("[경고] 업데이트할 연산 결과가 존재하지 않습니다.")

if __name__ == "__main__":
    main()
