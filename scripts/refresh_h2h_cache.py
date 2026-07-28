# football-data.co.uk(유럽 4대리그) + FotMob(K리그1/2) 과거 경기를 모아 h2h_cache.json을 재생성한다.
# 실행: python scripts/refresh_h2h_cache.py  (레포 루트에서 h2h_cache.json을 덮어씀)
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "h2h_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://www.fotmob.com/",
}
NEXT_DATA_START = '<script id="__NEXT_DATA__" type="application/json">'

EURO_LEAGUES = {"E0": "EPL", "SP1": "라리가", "I1": "세리에A", "D1": "분데스리가"}
EURO_SEASONS = ["2526", "2425", "2324", "2223", "2122", "2021"]
KLEAGUE_IDS = {"K리그1": 9080, "K리그2": 9116}
KLEAGUE_NUM_SEASONS = 6


def fetch_next_data(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    i = r.text.find(NEXT_DATA_START)
    if i == -1:
        return None
    j = r.text.find("</script>", i)
    return json.loads(r.text[i + len(NEXT_DATA_START): j])


def collect_euro():
    rows = []
    for code, league in EURO_LEAGUES.items():
        for season in EURO_SEASONS:
            url = f"https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
            try:
                df = pd.read_csv(url, encoding="latin-1")
            except Exception as e:
                print(f"  skip {code} {season}: {e}")
                continue
            df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR"])
            for _, r in df.iterrows():
                rows.append({"league": league, "home": r["HomeTeam"], "away": r["AwayTeam"],
                             "hg": int(r["FTHG"]), "ag": int(r["FTAG"]),
                             "date": pd.to_datetime(r["Date"], dayfirst=True, errors="coerce")})
    return rows


def collect_kleague():
    rows = []
    for league, league_id in KLEAGUE_IDS.items():
        data0 = fetch_next_data(f"https://www.fotmob.com/ko/leagues/{league_id}/overview/")
        seasons = data0["props"]["pageProps"].get("allAvailableSeasons", [])[:KLEAGUE_NUM_SEASONS] if data0 else []
        for season in seasons:
            data = fetch_next_data(f"https://www.fotmob.com/ko/leagues/{league_id}/overview/?season={season}")
            if not data:
                continue
            fx = data["props"]["pageProps"].get("fixtures", {})
            matches = fx.get("allMatches", []) if isinstance(fx, dict) else []
            for m in matches:
                status = m.get("status", {})
                if not status.get("finished"):
                    continue
                score = status.get("scoreStr", "")
                if "-" not in score:
                    continue
                hs, as_ = score.split("-")
                if not (hs.strip().isdigit() and as_.strip().isdigit()):
                    continue
                home, away = m.get("home", {}).get("name"), m.get("away", {}).get("name")
                date = str(status.get("utcTime", "")).split("T")[0]
                if home and away and date:
                    rows.append({"league": league, "home": home, "away": away,
                                 "hg": int(hs), "ag": int(as_), "date": pd.to_datetime(date)})
            time.sleep(0.4)
    return rows


def main():
    rows = collect_euro() + collect_kleague()
    df = pd.DataFrame(rows).dropna(subset=["date"]).sort_values(["league", "date"])

    cache = {}
    for _, row in df.iterrows():
        key = f"{row['league']}|" + "|".join(sorted([row["home"], row["away"]]))
        cache.setdefault(key, []).append({
            "date": row["date"].strftime("%Y-%m-%d"), "home": row["home"],
            "hg": int(row["hg"]), "ag": int(row["ag"]),
        })
    for k in cache:
        cache[k] = cache[k][-5:]

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"pairs={len(cache)} matches_indexed={len(df)} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
