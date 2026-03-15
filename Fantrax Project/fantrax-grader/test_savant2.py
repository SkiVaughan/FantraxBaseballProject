import requests
import pandas as pd
from io import StringIO

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Check all columns available in pitcher CSV
resp = requests.get(
    "https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=pitcher&filter=&min=25&csv=true",
    headers=HEADERS, timeout=20
)
df = pd.read_csv(StringIO(resp.text))
print("All pitcher columns:")
print(list(df.columns))
print("\nFirst row sample:")
print(df.iloc[0].to_dict())
