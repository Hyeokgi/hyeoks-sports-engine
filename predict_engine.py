import os
import json
import pandas as pd
import numpy as np
import gspread
import requests
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from sklearn.ensemble import RandomForestClassifier

FEATURES = [
    "전력차 지표(Elo)",
    "공격격차 지표(득점)",
    "수비격차 지표(실점)",
    "방어안정성(클린시트)",
    "상대전적 격차(H2H)",
]

# 2026-07-30: K리그1/K리그2는 RandomForest 대신 kleague-toto-predictor 앱(Elo+최근폼+
# 상대전적+해외배당 블렌딩, 이 세션에서 직접 백테스트/검증됨)의 예측을 그대로 가져와 쓴다.
# 두 시스템이 서로 다른 확률을 보여주는 걸 사용자가 확인하고 요청한 통일 작업.
KLEAGUE_APP_BASE_URL = "https://kleague-toto-predictor.hyeoks.workers.dev"

NAME_MAP = {
    "강원FC": "Gangwon FC", "부천FC": "Bucheon FC 1995",
    "전북현대": "Jeonbuk Hyundai Motors FC", "FC서울": "FC Seoul",
    "포항스틸": "Pohang Steelers", "김천상무": "Gimcheon Sangmu",
    "충남아산": "Chungnam Asan FC", "성남FC": "Seongnam FC",
    "천안시티": "Cheonan City", "용인FC": "Yongin FC",
    "충북청주": "Cheongju FC", "수원삼성": "Suwon Samsung Bluewings",
    "화성FC": "Hwaseong FC", "대구FC": "Daegu FC",
    "울산HDFC": "Ulsan HD FC", "FC안양": "FC Anyang",
    "대전하나": "Daejeon Hana Citizen", "광주FC": "Gwangju FC",
    "제주SKFC": "Jeju SK", "인천유나": "Incheon United",
    "부산아이": "Busan I'Park", "서울이랜": "Seoul E-Land FC",
    "김포FC": "Gimpo FC", "경남FC": "Gyeongnam FC",
    "전남드래": "Jeonnam Dragons", "파주프런": "Paju Frontier",
    "안산그리": "Ansan Greeners", "김해FC": "Gimhae FC 2008",
    "수원FC": "Suwon FC",
    # J1리그(일본, kleague-toto-predictor 앱에 2026-08 편입된 팀명 매핑과 동일)
    "FC도쿄": "FC Tokyo", "마치다Z": "Machida Zelvia",
    "나고야G": "Nagoya Grampus", "시미즈S": "Shimizu S-Pulse",
    "C오사카": "Cerezo Osaka", "오카야마": "Fagiano Okayama FC",
    "후쿠오카": "Avispa Fukuoka", "비셀고베": "Vissel Kobe",
    "산프히로": "Sanfrecce Hiroshima", "제프유나": "JEF United Chiba",
    "도쿄베르": "Tokyo Verdy", "가와사키": "Kawasaki Frontale",
    "V바렌나": "V-Varen Nagasaki", "교토상가": "Kyoto Sanga FC",
    "감바오사카": "Gamba Osaka", "가시마": "Kashima Antlers",
    "가시와": "Kashiwa Reysol", "미토": "Mito Hollyhock",
    "우라와": "Urawa Red Diamonds", "요코하마M": "Yokohama F.Marinos",
}


def fetch_kleague_predictions():
    """배포된 kleague-toto-predictor 앱의 최신 회차 예측을 (영문홈팀,영문원정팀) 키로 반환.
    앱이 응답하지 않으면 빈 dict를 반환해 해당 경기는 RandomForest로 자연스럽게 대체된다."""
    try:
        rounds_res = requests.get(f"{KLEAGUE_APP_BASE_URL}/api/rounds", timeout=10)
        rounds_res.raise_for_status()
        rounds = rounds_res.json().get("rounds", [])
        if not rounds:
            return {}
        round_id = rounds[0]["id"]
        detail_res = requests.get(f"{KLEAGUE_APP_BASE_URL}/api/rounds/{round_id}", timeout=10)
        detail_res.raise_for_status()
        lookup = {}
        for m in detail_res.json().get("matches", []):
            home_en, away_en = NAME_MAP.get(m["home"]), NAME_MAP.get(m["away"])
            if not home_en or not away_en:
                continue
            p = m["prediction"]
            lookup[(home_en, away_en)] = {
                "p_home": round(p["pHome"] * 100, 1),
                "p_draw": round(p["pDraw"] * 100, 1),
                "p_away": round(p["pAway"] * 100, 1),
            }
        return lookup
    except Exception as e:
        print(f"⚠️ kleague-toto-predictor 앱 예측 조회 실패, 해당 경기는 RandomForest로 대체: {e}")
        return {}

def init_google_sheet():
    secret_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    credentials_dict = json.loads(secret_key)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scopes)
    gc = gspread.authorize(creds)
    return gc.open("HYEOKS_Sports_Toto_Data")

def main():
    print("======== [HYEOKS 타이 브레이커 보정 예측 두뇌 v3.6 가동] ========")
    sh = init_google_sheet()
    
    total_sheet = sh.worksheet("전체")
    raw_records = total_sheet.get_all_records()
    df = pd.DataFrame(raw_records)
    
    if df.empty:
        print("❌ '전체' 탭에 학습 소스 데이터가 전무합니다.")
        return
        
    for col in FEATURES:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    def determine_target(row):
        h_score = str(row['홈스코어']).strip()
        a_score = str(row['원정스코어']).strip()
        if h_score == "" or a_score == "" or h_score == "None" or a_score == "None":
            return None
        try:
            h, a = float(h_score), float(a_score)
            if h > a: return 2
            elif h < a: return 0
            else: return 1
        except: return None

    df['target'] = df.apply(determine_target, axis=1)
    
    df['date_obj'] = pd.to_datetime(df['일시'], errors='coerce')
    current_date = pd.to_datetime('2026-07-28')
    df['days_ago'] = (current_date - df['date_obj']).dt.days
    
    train_df = df[df['target'].notna()].copy()
    predict_df = df[df['target'].isna()].copy()
    
    if train_df.empty:
        print("⚠️ 학습 가능한 완료 경기 레코드가 존재하지 않습니다.")
        return
    if predict_df.empty:
        print("💡 분석 대상이 되는 미래 경기가 없어 리포트를 종결합니다.")
        return
        
    train_df['sample_weight'] = np.exp(-0.0005 * train_df['days_ago'].fillna(0))
    
    X_train = train_df[FEATURES]
    y_train = train_df['target'].astype(int)
    weights = train_df['sample_weight']
    
    model = RandomForestClassifier(
        n_estimators=200, 
        max_depth=5, 
        class_weight="balanced_subsample", 
        random_state=42
    )
    model.fit(X_train, y_train, sample_weight=weights)
    
    X_predict = predict_df[FEATURES]
    raw_probabilities = model.predict_proba(X_predict)

    kleague_lookup = fetch_kleague_predictions()
    kleague_used, randomforest_used = 0, 0
    calibrated_results = []

    for idx, (_, row) in enumerate(predict_df.iterrows()):
        app_pred = kleague_lookup.get((str(row['홈팀']), str(row['원정팀'])))
        if app_pred:
            prob_home, prob_draw, prob_away = app_pred['p_home'], app_pred['p_draw'], app_pred['p_away']
            kleague_used += 1
        else:
            p_away = raw_probabilities[idx][0]
            p_draw = raw_probabilities[idx][1] * 0.75
            p_home = raw_probabilities[idx][2]

            total_p = p_away + p_draw + p_home
            prob_away = round((p_away / total_p) * 100, 1)
            prob_draw = round(((p_draw / total_p)) * 100, 1)
            prob_home = round((p_home / total_p) * 100, 1)
            randomforest_used += 1

        elo_val = float(row['전력차 지표(Elo)'])
        
        if prob_home == prob_away:
            if elo_val > 15.0: pick = "홈승(▲)"
            elif elo_val < -15.0: pick = "원정승(▼)"
            else: pick = "무승부(■)"
        else:
            arr = [prob_away, prob_draw, prob_home]
            am = np.argmax(arr)
            pick = "원정승(▼)" if am == 0 else ("무승부(■)" if am == 1 else "홈승(▲)")
        
        prediction_results_row = [
            str(row['경기ID']), str(row['일시']), str(row['리그']), str(row['홈팀']), str(row['원정팀']),
            f"{prob_home}%", f"{prob_draw}%", f"{prob_away}%", pick,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ]
        calibrated_results.append(prediction_results_row)
    
    print(f" 📊 예측 소스: kleague-toto-predictor 앱 {kleague_used}건, RandomForest {randomforest_used}건")
    calibrated_results.sort(key=lambda x: x[1])
    
    report_headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈승 확률", "무승부 확률", "원정승 확률", "예측 추천픽", "예측 분석시각"]
    
    try: report_sheet = sh.worksheet("HYEOKS_예측리포트")
    except gspread.WorksheetNotFound: report_sheet = sh.add_worksheet(title="HYEOKS_예측리포트", rows="500", cols="15")
        
    report_sheet.clear()
    report_sheet.append_row(report_headers)
    report_sheet.append_rows(calibrated_results)
    
    print(f" 🎉 [대성공] 타이 브레이커 밸런싱 교정 완료! 'HYEOKS_예측리포트' 동기화 성공.")

if __name__ == "__main__":
    main()
