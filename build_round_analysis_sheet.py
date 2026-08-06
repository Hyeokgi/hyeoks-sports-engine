# 회차별 투표율/모델예측/실제결과 비교를 구글시트 "HYEOKS_회차분석" 탭에 기록(append-only, 매번 clear+재기록).
# 1~41회차: betman 과거기록 파일(투표 vs 실제결과, 2축 - 그 시절엔 우리 모델이 없었음).
# 42회차~: kleague-toto-predictor 앱 API(투표+모델예측+실제결과, 3축 - round_results/round_vote_share
# 정산 인프라가 생긴 이후). 두 구간은 데이터 출처가 달라 같은 시트에 컬럼을 맞춰 이어붙인다.
import json
import os
from pathlib import Path

import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials

ROOT = Path(__file__).resolve().parent
RESULT_MAP = {"승": "홈승", "무": "무승부", "패": "원정승"}
ACTUAL_LABEL = {"H": "홈승", "D": "무승부", "A": "원정승"}
KLEAGUE_APP_BASE_URL = "https://kleague-toto-predictor.hyeoks.workers.dev"

HEADERS = [
    "회차", "경기번호", "일시", "홈팀", "원정팀", "홈스코어", "원정스코어", "실제결과",
    "투표1위", "투표1위 득표율(%)", "실제결과 득표율(%)", "투표기준 이변여부",
    "모델픽", "모델확신도(%p)", "모델확신도등급", "구간 실측적중률(%, 참고용)", "모델기준 이변여부",
    "데이터출처",
]


def init_google_sheet():
    secret_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    credentials_dict = json.loads(secret_key)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scopes)
    gc = gspread.authorize(creds)
    return gc.open("HYEOKS_Sports_Toto_Data")


def build_historical_rows():
    """1~41회차: betman 과거기록 파일 기반, 2축(투표 vs 실제결과).
    모델 예측 컬럼은 그 시절 앱이 없어 원래 공란이었지만, K리그1/K리그2/J1리그 경기에 한해
    2026-08-06에 point-in-time(그 경기 이전 데이터만 사용, look-ahead 없음) walk-forward
    재구성을 해서 data/retro_model_picks_1_41.json으로 채웠다(574경기 중 63건, 나머지는
    EPL/세리에A 등 유럽리그라 우리 시스템에 다중시즌 Elo 히스토리가 없어 재구성 불가)."""
    with open(ROOT / "data" / "toto_rounds_raw.json", encoding="utf-8") as f:
        rounds = json.load(f)
    with open(ROOT / "data" / "toto_votes_raw.json", encoding="utf-8") as f:
        votes = json.load(f)
    retro_path = ROOT / "data" / "retro_model_picks_1_41.json"
    retro_lookup = {}
    if retro_path.exists():
        with open(retro_path, encoding="utf-8") as f:
            for row in json.load(f):
                retro_lookup[(row["round"], row["seq"])] = row

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

            retro = retro_lookup.get((rnum, m["seq"]))
            if retro:
                model_pick, conf_gap, tier = retro["model_pick"], retro["conf_gap_pct"], retro["tier"]
                calib_acc = retro["calib_accuracy_pct"]
                model_upset = "이변" if retro["model_upset"] else ""
                source = "betman 과거기록 + 회고재구성모델(2026-08-06)"
            else:
                model_pick = conf_gap = tier = calib_acc = model_upset = ""
                source = "betman 과거기록(1~41회차)"

            rows.append([
                rnum, m["seq"], m["date"], m["home"], m["away"],
                m["hg"], m["ag"], actual,
                fav, round(votes3[fav], 1), round(votes3[actual], 1),
                "이변" if actual != fav else "",
                model_pick, conf_gap, tier, calib_acc, model_upset,
                source,
            ])
    if skipped_mismatch:
        print(f"경고: 팀명 불일치로 {skipped_mismatch}건 제외함 (betman 원본 소스 자체의 순서 불일치)")
    return rows


def build_app_rows():
    """42회차~: kleague-toto-predictor 앱 API 기반, 실제결과가 확정된(정산된) 경기만 3축으로 기록."""
    rows = []
    try:
        rounds_res = requests.get(f"{KLEAGUE_APP_BASE_URL}/api/rounds", timeout=10)
        rounds_res.raise_for_status()
        rounds = rounds_res.json().get("rounds", [])
    except Exception as e:
        print(f"⚠️ 앱 회차 목록 조회 실패, 42회차~ 구간은 건너뜀: {e}")
        return rows

    for round_info in rounds:
        if not round_info.get("round_no_confirmed"):
            continue
        round_id = round_info["id"]
        round_no = round_info["round_no"]
        try:
            detail_res = requests.get(f"{KLEAGUE_APP_BASE_URL}/api/rounds/{round_id}", timeout=10)
            detail_res.raise_for_status()
            matches = detail_res.json().get("matches", [])
        except Exception as e:
            print(f"⚠️ {round_no}회차 상세 조회 실패, 스킵: {e}")
            continue

        for m in matches:
            result = m.get("result")
            if not result:
                continue  # 아직 경기가 안 끝났거나 정산 전 - 이 시트는 확정된 결과만 기록
            actual = ACTUAL_LABEL[result["actual"]]
            p = m["prediction"]
            model_pick = p["rankedPicks"][0]
            conf_gap = round(p["confidenceGap"] * 100, 1)
            calib = m.get("calibration") or {}
            tier = calib.get("tier", "")
            bucket = calib.get("bucket")
            calib_accuracy = round(bucket["accuracy"] * 100, 1) if bucket else ""

            vote = m.get("voteShare")
            if vote:
                votes3 = {"홈승": vote["home"], "무승부": vote["draw"], "원정승": vote["away"]}
                vote_fav = max(votes3, key=votes3.get)
                vote_fav_pct = round(votes3[vote_fav], 1)
                actual_share_pct = round(votes3[actual], 1)
                vote_upset = "이변" if actual != vote_fav else ""
            else:
                vote_fav = vote_fav_pct = actual_share_pct = vote_upset = ""

            rows.append([
                round_no, m["seq"], m.get("kickoff_at") or "", m["home"], m["away"],
                result["hg"], result["ag"], actual,
                vote_fav, vote_fav_pct, actual_share_pct, vote_upset,
                model_pick, conf_gap, tier, calib_accuracy,
                "이변" if actual != model_pick else "",
                "kleague-toto-predictor 앱(42회차~)",
            ])
    return rows


def main():
    sh = init_google_sheet()
    rows = build_historical_rows() + build_app_rows()
    try:
        ws = sh.worksheet("HYEOKS_회차분석")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="HYEOKS_회차분석", rows=str(len(rows) + 10), cols=str(len(HEADERS)))
    ws.clear()
    ws.append_row(HEADERS)
    ws.append_rows(rows)
    print(f"HYEOKS_회차분석: {len(rows)}행 기록 완료")


if __name__ == "__main__":
    main()
