import os
import json
import pandas as pd
import numpy as np
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from sklearn.ensemble import RandomForestClassifier

# -------------------------------------------------------------------------
# 💡 [확장성 보장] 나중에 변수를 추가할 때 여기 리스트에 컬럼 이름만 더해두면 끝납니다!
# -------------------------------------------------------------------------
FEATURES = [
    "전력차 지표(Elo)", 
    "공격격차 지표(득점)", 
    "수비격차 지표(실점)", 
    "방어안정성(클린시트)"
    # 예: "날씨_온도", "상대전적_지표" 등 추가 변수 발생 시 여기에 컬럼명 적기
]

def init_google_sheet():
    secret_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    credentials_dict = json.loads(secret_key)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scopes)
    gc = gspread.authorize(creds)
    return gc.open("HYEOKS_Sports_Toto_Data")

def main():
    print("======== [HYEOKS 머신러닝 예측 두뇌 가동] ========")
    sh = init_google_sheet()
    
    # 1. '전체' 탭에서 학습 소스 데이터 로드
    total_sheet = sh.worksheet("전체")
    raw_records = total_sheet.get_all_records()
    df = pd.DataFrame(raw_records)
    
    if df.empty:
        print("❌ 학습할 데이터가 '전체' 탭에 존재하지 않습니다.")
        return
        
    # 데이터 변수 형변환 및 정제
    for col in FEATURES:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    # 정답 라벨 정의 함수 (홈승: 2, 무승부: 1, 원정승: 0)
    def determine_target(row):
        h_score = str(row['홈스코어']).strip()
        a_score = str(row['원정스코어']).strip()
        if h_score == "" or a_score == "" or h_score == "None" or a_score == "None":
            return None
        try:
            h = float(h_score)
            a = float(a_score)
            if h > a: return 2
            elif h < a: return 0
            else: return 1
        except:
            return None

    df['target'] = df.apply(determine_target, axis=1)
    
    # 2. 데이터셋 분리 (학습용 vs 미래 예측용)
    train_df = df[df['target'].notna()].copy()
    predict_df = df[df['target'].isna()].copy()
    
    if train_df.empty:
        print("⚠️ 스코어가 기록된 완료 경리가 없어 모델 학습이 불가능합니다.")
        return
    if predict_df.empty:
        print("💡 현재 예정된 미래 경기가 없어 예측 리포트를 생성하지 않습니다.")
        return
        
    print(f" 📊 학습에 활용되는 완료 경기 데이터 수: {len(train_df)}개")
    print(f" 🔮 예측 대상이 되는 미래 경기 데이터 수: {len(predict_df)}개")
    
    # 3. 모델 학습 (수학적 과적합 방어용 Random Forest 엔진 배치)
    X_train = train_df[FEATURES]
    y_train = train_df['target'].astype(int)
    
    model = RandomForestClassifier(n_estimators=150, max_depth=6, random_state=42)
    model.fit(X_train, y_train)
    
    # 4. 미래 경기 확률 연산
    X_predict = predict_df[FEATURES]
    probabilities = model.predict_proba(X_predict) # [원정승확률, 무승부확률, 홈승확률] 순서 반환
    
    prediction_results = []
    for idx, (_, row) in enumerate(predict_df.iterrows()):
        prob_away = round(probabilities[idx][0] * 100, 1)
        prob_draw = round(probabilities[idx][1] * 100, 1)
        prob_home = round(probabilities[idx][2] * 100, 1)
        
        # 가장 확률이 높은 쪽을 추천 픽으로 제안
        am = np.argmax(probabilities[idx])
        pick = "홈승(▲)" if am == 2 else ("원정승(▼)" if am == 0 else "무승부(■)")
        
        prediction_results.append([
            str(row['경기ID']),
            str(row['일시']),
            str(row['리그']),
            str(row['홈팀']),
            str(row['원정팀']),
            f"{prob_home}%",
            f"{prob_draw}%",
            f"{prob_away}%",
            pick,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    # 날짜 최신순으로 정렬하여 리포트 적재 준비
    prediction_results.sort(key=lambda x: x[1])
    
    # 5. 구글 시트 'HYEOKS_예측리포트' 탭 생성 및 전송
    report_headers = ["경기ID", "일시", "리그", "홈팀", "원정팀", "홈승 확률", "무승부 확률", "원정승 확률", "예측 추천픽", "예측 분석시각"]
    
    try:
        report_sheet = sh.worksheet("HYEOKS_예측리포트")
    except gspread.WorksheetNotFound:
        report_sheet = sh.add_worksheet(title="HYEOKS_예측리포트", rows="500", cols="15")
        
    report_sheet.clear()
    report_sheet.append_row(report_headers)
    report_sheet.append_rows(prediction_results)
    
    print(" 🎉 [대성공] 머신러닝 예측 완료! 구글 시트 'HYEOKS_예측리포트' 탭을 확인하세요.")

if __name__ == "__main__":
    main()
