import os
import json
import pandas as pd
import numpy as np
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from sklearn.ensemble import RandomForestClassifier

FEATURES = [
    "전력차 지표(Elo)", 
    "공격격차 지표(득점)", 
    "수비격차 지표(실점)", 
    "방어안정성(클린시트)"
]

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
    
    calibrated_results = []
    
    for idx, (_, row) in enumerate(predict_df.iterrows()):
        p_away = raw_probabilities[idx][0]
        p_draw = raw_probabilities[idx][1] * 0.75 
        p_home = raw_probabilities[idx][2]
        
        total_p = p_away + p_draw + p_home
        prob_away = round((p_away / total_p) * 100, 1)
        prob_draw = round(((p_draw / total_p)) * 100, 1)
        prob_home = round((p_home / total_p) * 100, 1)
        
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
