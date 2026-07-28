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
# 2. FotMob 실시간 데이터 API 크롤러 (수정본)
# -------------------------------------------------------------------------
def fetch_fotmob_league_data(league_id="9116"):
    """FotMob 내부 API를 통해 리그 데이터(순위표, 경기 일정)를 가져옵니다."""
    # leagues -> league (단수형)으로 주소 수정
    url = f"https://www.fotmob.com/api/league?id={league_id}&ccode3=KOR"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"FotMob API 접근 실패: 상태 코드 {response.status_code}")
        return None
    return response.json()

# -------------------------------------------------------------------------
# 3. HYEOKS 엔진 고도화 변수 연산 (시뮬레이션 로직)
# -------------------------------------------------------------------------
def analyze_matches(data):
    if not data or 'fixtures' not in data or 'allMatches' not in data['fixtures']:
        return []
    
    # 팀별 기본 스탯 매핑 테이블 빌드 (순위표 기반 데이터 추출)
    team_stats = {}
    if 'table' in data and len(data['table']) > 0:
        # 일반적인 리그 테이블 구조 파싱
        table_data = data['table'][0].get('data', {}).get('table', [])
        for row in table_data:
            t_name = row.get('name')
            team_stats[t_name] = {
                'rank': row.get('idx'),
                'pts': row.get('pts'),
                'deduction': row.get('deduction', 0)
            }

    processed_rows = []
    matches = data['fixtures']['allMatches']
    
    for match in matches:
        # 경기본질 정보
        match_id = match.get('id')
        status = match.get('status', {})
        
        # 이미 종료된 경기이거나 오늘/내일 열릴 대진만 타겟팅
        date_str = match.get('pageUrl', '').split('/')[-1] # 임시 날짜 파싱 규칙
        home_team = match.get('home', {}).get('name')
        away_team = match.get('away', {}).get('name')
        
        # 스코어 처리
        home_score = status.get('scoreStr', '').split('-')[0].strip() if status.get('finished') else ""
        away_score = status.get('scoreStr', '').split('-')[1].strip() if status.get('finished') else ""
        
        # [고도화 변수 1] 팀 체급 전력차 (Power Difference)
        # 평점 시스템 대용으로 현재 순위와 승점 기반 전력 지표 가공
        home_pts = team_stats.get(home_team, {}).get('pts', 15) # 데이터 공백 시 기본값
        away_pts = team_stats.get(away_team, {}).get('pts', 15)
        power_diff = round(float(home_pts - away_pts), 2)
        
        # [고도화 변수 2] 가상 H2H(상대전적) 및 전술 상성 인덱스 
        # API에서 제공하는 최근 폼(Form) 데이터를 대리 변수로 가공
        home_form = match.get('home', {}).get('form', [])
        away_form = match.get('away', {}).get('form', [])
        
        # 최근 폼 점수 환산 (최근 경기 승리 가중치)
        def calculate_form_score(form_list):
            score = 0.0
            for idx, f in enumerate(form_list[:5]):
                weight = 1.0 - (idx * 0.1) # 최근 경기일수록 가중치 높음
                if f == 'W': score += 3.0 * weight
                elif f == 'D': score += 1.0 * weight
            return round(score, 2)
            
        h2h_index = round(calculate_form_score(home_form) - calculate_form_score(away_form), 2)
        
        # [고도화 변수 3] 전술 매칭 아키타입 (Style Alignment)
        # 상위권 팀과 하위권 팀의 대결 양상을 스타일 카테고리로 강제 분류
        home_rank = team_stats.get(home_team, {}).get('rank', 5)
        away_rank = team_stats.get(away_team, {}).get('rank', 5)
        if home_rank <= 4 and away_rank >= 8:
            tactical_match = "주도 vs 역습"
        elif home_rank >= 8 and away_rank <= 4:
            tactical_match = "역습 vs 주도"
        else:
            tactical_match = "균형 vs 균형"

        # 구글 시트에 들어갈 최종 데이터 행 정의
        processed_rows.append([
            str(match_id),
            str(match.get('timeStr', datetime.now().strftime('%Y-%m-%d'))),
            "K리그2",
            home_team,
            away_team,
            str(home_score),
            str(away_score),
            str(power_diff),      # 변수 1: 체급 차이
            str(h2h_index),       # 변수 2: 최근 상성 지표
            tactical_match,       # 변수 3: 전술 궁합
            datetime.now().strftime('%Y-%m-%d %H:%M:%S') # 갱신 시각
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
