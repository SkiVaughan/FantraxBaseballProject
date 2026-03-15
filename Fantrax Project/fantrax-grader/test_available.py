import auth
from fantraxapi import League

league = League("hp3gi9z9mg6wf2p7")
session = league.session

payload = {
    "msgs": [{
        "method": "getAvailablePlayers",
        "data": {
            "leagueId": "hp3gi9z9mg6wf2p7",
            "statusOrTeamFilter": "ALL_AVAILABLE",
            "pageNumber": "1",
            "maxResultsPerPage": "500",
            "sortType": "SCORE",
            "view": "STATS",
        },
    }]
}

import requests
resp = session.post(
    "https://www.fantrax.com/fxpa/req",
    params={"leagueId": "hp3gi9z9mg6wf2p7"},
    json=payload,
    timeout=20,
)
import auth
from fantraxapi import League
import json

league = League("hp3gi9z9mg6wf2p7")
session = league.session

payload = {
    "msgs": [{
        "method": "getPlayerStats",
        "data": {
            "leagueId": "hp3gi9z9mg6wf2p7",
            "reload": "1",
            "statusOrTeamFilter": "ALL_AVAILABLE",
            "pageNumber": "1",
            "maxResultsPerPage": "50",
            "view": "STATS",
        },
    }]
}

resp = session.post(
    "https://www.fantrax.com/fxpa/req",
    params={"leagueId": "hp3gi9z9mg6wf2p7"},
    json=payload,
    timeout=20,
)
data = resp.json()
top = data["responses"][0]["data"]

# Inspect first 3 players
for row in top["statsTable"][:3]:
    print("--- Player ---")
    print("scorer keys:", list(row["scorer"].keys()))
    print("name:", row["scorer"].get("name"))
    print("actions:", row.get("actions"))
    print("scorer sample:", json.dumps({k: row["scorer"][k] for k in list(row["scorer"].keys())[:10]}, indent=2))
    print()

