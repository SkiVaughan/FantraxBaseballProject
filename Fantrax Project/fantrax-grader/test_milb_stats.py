"""Quick test to see what MiLB stats are available from the MLB Stats API"""
import requests
import json

# Test fetching minor league stats for a known prospect
# Blake Mitchell - KC Royals prospect
resp = requests.get(
    "https://statsapi.mlb.com/api/v1/people/search",
    params={"names": "Blake Mitchell", "sportIds": "11,12,13,14,16"},
    timeout=10,
)
print("Search status:", resp.status_code)
print(json.dumps(resp.json(), indent=2)[:1000])

# Try fetching all AAA/AA hitter stats
resp2 = requests.get(
    "https://statsapi.mlb.com/api/v1/stats",
    params={
        "stats": "season",
        "group": "hitting",
        "sportIds": "11,12",  # AAA + AA
        "season": 2024,
        "limit": 10,
        "offset": 0,
    },
    timeout=15,
)
print("\nStats status:", resp2.status_code)
data = resp2.json()
print("Keys:", list(data.keys()))
if "stats" in data:
    splits = data["stats"][0].get("splits", [])
    print(f"Splits: {len(splits)}")
    if splits:
        print("First split keys:", list(splits[0].keys()))
        print("First player:", splits[0].get("player", {}).get("fullName"))
        print("First stat:", json.dumps(splits[0].get("stat", {}), indent=2)[:300])
