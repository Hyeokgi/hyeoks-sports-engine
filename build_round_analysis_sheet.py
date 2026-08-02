# 1~41회차 투표율 vs 실제결과를 구글시트 "HYEOKS_회차분석" 탭에 기록 (append-only, 매번 clear+재기록).
# 42회차부터는 kleague-toto-predictor 앱의 시스템예측치도 존재하지만, 그 회차의 투표율 원본
# 데이터(toto_votes_raw.json)에는 아직 없어 이번 단계는 1~41회차 2축(투표율 vs 실제결과) 비교로 한정한다.
import json
import os
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials

ROOT = Path(__file__).resolve().parent
RESULT_MAP = {"승": "홈승", "무": "무승부", "패": "원정승"}


def init_google_sheet():
    secret_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    credentials_dict = json.loads(secret_key)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scopes)
    gc = gspread.authorize(creds)
    return gc.open("HYEOKS_Sports_Toto_Data")


def build_rows():
    with open(ROOT / "data" / "toto_rounds_raw.json", encoding="utf-8") as f:
        rounds = json.load(f)
    with open(ROOT / "data" / "toto_votes_raw.json", encoding="utf-8") as f:
        votes = json.load(f)

    rows = []
    skipped_mismatch = 0
    for r in rounds:
        rnum = int(r["round"].split()[2].replace("회차", ""))
        vote_lookup = {m["seq"]: m for m in votes.get(str(rnum), {}).get("matches", [])}
        for m in r["matches"]:
            if m["result"] not in RESULT_MAP:
                continue
            v = vote_lookup.get(m["seq"])
            if not v or v.get("voteWin") is None:
                continue
            if m["home"] != v["home"] or m["away"] != v["away"]:
                skipped_mismatch += 1
                continue
            actual = RESULT_MAP[m["result"]]
            votes3 = {"홈승": v["voteWin"], "무승부": v["voteDraw"], "원정승": v["voteLose"]}
            fav = max(votes3, key=votes3.get)
            rows.append([
                rnum, m["seq"], m["date"], m["home"], m["away"],
                m["hg"], m["ag"], actual,
                fav, round(votes3[fav], 1), round(votes3[actual], 1),
                "이변" if actual != fav else "",
            ])
    if skipped_mismatch:
        print(f"경고: 팀명 불일치로 {skipped_mismatch}건 제외함 (betman 원본 소스 자체의 순서 불일치)")
    return rows


def main():
    sh = init_google_sheet()
    headers = [
        "회차", "경기번호", "일시", "홈팀", "원정팀", "홈스코어", "원정스코어", "실제결과",
        "투표1위", "투표1위 득표율(%)", "실제결과 득표율(%)", "이변여부",
    ]
    rows = build_rows()
    try:
        ws = sh.worksheet("HYEOKS_회차분석")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="HYEOKS_회차분석", rows=str(len(rows) + 10), cols=str(len(headers)))
    ws.clear()
    ws.append_row(headers)
    ws.append_rows(rows)
    print(f"HYEOKS_회차분석: {len(rows)}행 기록 완료 (1~41회차, 투표율 vs 실제결과)")


if __name__ == "__main__":
    main()
