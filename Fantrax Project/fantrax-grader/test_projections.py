"""
Test pulling projections + multi-year Fantrax scores.
"""
import auth
from fantraxapi import League

league = League("hp3gi9z9mg6wf2p7")
session = league.session

def get_season_scores(season_code: str, label: str):
    payload = {
        "msgs": [{
            "method": "getPlayerStats",
            "data": {
                "leagueId": "hp3gi9z9mg6wf2p7",
                "reload": "1",
                "statusOrTeamFilter": "ALL",
                "pageNumber": "1",
                "maxResultsPerPage": "20",
                "view": "STATS",
                "sortType": "SCORE",
                "seasonOrProjection": season_code,
            },
        }]
    }
    resp = session.post(
        "https://www.fantrax.com/fxpa/req",
        params={"leagueId": "hp3gi9z9mg6wf2p7"},
        json=payload, timeout=20,
    )
    data = resp.json()
    top = data["responses"][0]["data"]
    print(f"\n=== {label} ({season_code}) ===")
    print(f"Header: {[c.get('shortName') for c in top.get('tableHeader',{}).get('cells',[])]}")
    for row in top["statsTable"][:5]:
        scorer = row["scorer"]
        cells = row["cells"]
        print(f"  {scorer['name']} ({scorer['posShortNames'].replace('<b>','').replace('</b>','')}) "
              f"— {[c.get('content','') for c in cells]}")

# Test each season + projections
get_season_scores("SEASON_145_YEAR_TO_DATE", "2025 Season")
get_season_scores("SEASON_143_YEAR_TO_DATE", "2024 Season")
get_season_scores("SEASON_141_YEAR_TO_DATE", "2023 Season")
get_season_scores("PROJECTION_0_147_SEASON", "2026 Projections")
