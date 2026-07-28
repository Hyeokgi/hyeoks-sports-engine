import os
import json
import pandas as pd
import numpy as np
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from sklearn.ensemble import RandomForestClassifier

# -------------------------------------------------------------------------
# 💡 [확장성 보장] 모델이 학습할 핵심 변수 레이어 (무승부율 피처 추가)
# -------------------------------------------------------------------------
FEATURES = [
    "전력차 지표(Elo)", 
    "공격격차 지표(득점)", 
    "수비격차 지표(실점)", 
    "방어안정성(클린시트)",
    "리그별_무승부율"  # 무승부 성향을 학습하기 위한 리그 고유 지표
]

def init_google_sheet():
    secret_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    credentials_dict = json.loads(secret_key)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scopes)
    gc = gspread.authorize(creds)
    return gc.open("HYEOKS_Sports_Toto_Data")

def main():
    print("======== [HYEOKS 머신러닝 시간가중치 엔진 v2.0 가동] ========")
    sh = init_google_sheet()
    
    total_sheet = sh.worksheet("전체")
    raw_records = total_sheet.get_all_records()
    df = pd.DataFrame(raw_records)
    
    if df.empty:
        print("❌ '전체' 탭에 학습 소스 데이터가 전무합니다.")
        return
        
    # 데이터 정제 및 형변환
    for col in ["전력차 지표(Elo)", "공격격차 지표(득점)", "수비격차 지표(실점)", "방어안정성(클린시트)"]:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    # 정답 셋업 (홈승: 2, 무승부: 1, 원정승: 0)
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
    
    # 💡 [피처 엔지니어링] 리그별 역사적 무승부 경향성 수치 도출
    league_draw_rates = {}
    for league in df['리그'].unique():
        league_df = df[(df['리그'] == league) & (df['target'].notna())]
        if len(league_df) > 0:
            draw_rate = len(league_df[league_df['target'] == 1]) / len(league_df)
        else:
            draw_rate = 0.28  # 데이터 공백 시 전세계 축구 평균 무승부 확률(28%) 준용
        league_draw_rates[league] = draw_rate
        
    df['리그별_무승부율'] = df['리그'].map(league_draw_rates)
    
    # 💡 [역대 3개년 시간 감쇠 가중치 연산]
    # 오늘 기준일(2026-07-28) 설정 후 경기 일자와의 거리 계산
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
        
    # 3년 이전의 너무 오래된 데이터 격리 방어 및 지수형 감쇠 가중치 함수 정의
    # w = exp(-0.0005 * days_ago) -> 최근 경기일수록 1.0에 수렴, 오래될수록 감소
    train_df['sample_weight'] = np.exp(-0.0005 * train_df['days_ago'].fillna(0))
    
    print(f" 📊 최신 가중치 적용 학습 완료 데이터 수: {len(train_df)}개")
    print(f" 🔮 미래 예측 대상 경기 데이터 수: {len(predict_df)}개")
    
    X_train = train_df[FEATURES]
    y_train = train_df['target'].astype(int)
    weights = train_df['sample_weight']
    
    # 모델 빌드 및 시간 가중치 주입 학습
    model = RandomForestClassifier(n_estimators=180, max_depth=6, random_state=42)
    model.fit(X_train, y_train, sample_weight=weights)
    
    # 미래 경기 예측 확률 산출
    X_predict = predict_df[FEATURES]
    probabilities = model.predict_proba(X_predict)
    
    prediction_results = []
    for idx, (_, row) in enumerate(predict_df.iterrows()):
        prob_away = round(probabilities[idx][0] * 100, 1)
        prob_draw = round(probabilities[idx][1] * 100, 1)
        prob_home = round(probabilities[idx][2] * 100, 1)
        
        am = np.argmax(probabilities[idx])
        pick = "홈승(▲)" if am == 2 else ("원정승(▼)" if am == 0 else "무승부(■)")
        
        prediction_results.append([
            str(row['경기ID']), str(row['일시']), str(row['리그']), str(row['홈팀']), str(row['원정팀']),
            f"{prob_home}%", f"{prob_draw}%", f"{prob_away}%", pick,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    prediction_results.sort(key=lambda x: x[1])
    
    report_headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈승 확률", "무승부 확률", "원정승 확률", "예측 추천픽", "예측 분석시각"]
    
    try: report_sheet = sh.worksheet("HYEOKS_예측리포트")
    except gspread.WorksheetNotFound: report_sheet = sh.add_worksheet(title="HYEOKS_예측리포트", rows="500", cols="15")
        
    report_sheet.clear()
    report_sheet.append_row(report_headers)
    report_sheet.append_rows(prediction_results)
    
    print(" 🎉 [대성공] 시간가중치 및 리그 무승부율 반영 예측 리포트가 시트에 동기화되었습니다.")

if __name__ == "__main__":
    main()
