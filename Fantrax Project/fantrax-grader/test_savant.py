import requests
import pandas as pd
from io import StringIO

# Test Savant CSV endpoints
endpoints = {
    "xwOBA/barrel (hitters)": "https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=batter&filter=&min=25&csv=true",
    "sprint_speed": "https://baseballsavant.mlb.com/leaderboard/sprint_speed?min_competitive_runs=10&position=&team=&csv=true",
    "xwOBA (pitchers)": "https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=pitcher&filter=&min=25&csv=true",
    "outs_above_avg": "https://baseballsavant.mlb.com/leaderboard/outs_above_average?type=Fielder&min=1&csv=true",
}

headers = {"User-Agent": "Mozilla/5.0"}

for name, url in endpoints.items():
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"\n{name}: status={resp.status_code}, size={len(resp.content)}")
        if resp.status_code == 200 and "," in resp.text[:100]:
            df = pd.read_csv(StringIO(resp.text))
            print(f"  Columns: {list(df.columns[:10])}")
            print(f"  Rows: {len(df)}")
            print(f"  Sample: {df.iloc[0][['last_name, first_name'] if 'last_name, first_name' in df.columns else df.columns[:3]].to_dict()}")
        else:
            print(f"  Not CSV: {resp.text[:200]}")
    except Exception as e:
        print(f"  ERROR: {e}")
