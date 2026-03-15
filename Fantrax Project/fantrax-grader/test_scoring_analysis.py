"""
Pull 2025 full season Fantrax scores to analyze position value.
"""
import auth
from fantraxapi import League
import pandas as pd

league = League("hp3gi9z9mg6wf2p7")
session = league.session

all_players = []
page = 1

while True:
    payload = {
        "msgs": [{
            "method": "getPlayerStats",
            "data": {
                "leagueId": "hp3gi9z9mg6wf2p7",
                "reload": "1",
                "statusOrTeamFilter": "ALL",
                "pageNumber": str(page),
                "maxResultsPerPage": "500",
                "view": "STATS",
                "sortType": "SCORE",
                "seasonOrProjection": "SEASON_145_YEAR_TO_DATE",  # 2025 full season
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

    for row in top["statsTable"]:
        scorer = row["scorer"]
        cells = row["cells"]
        # cells: Rk, Sta, Age, Opp, FPts, FP/G, Ros, +/-
        try:
            fpts = float(cells[4]["content"]) if cells[4]["content"] else 0
            fpg  = float(cells[5]["content"]) if cells[5]["content"] else 0
        except (IndexError, ValueError):
            fpts, fpg = 0, 0

        all_players.append({
            "name": scorer["name"],
            "position": scorer["posShortNames"].replace("<b>","").replace("</b>",""),
            "primary_pos": scorer.get("defaultPosId",""),
            "age": scorer.get("age", None),
            "fpts_2025": fpts,
            "fpg_2025": fpg,
            "minors_eligible": scorer.get("minorsEligible", False),
        })

    pagination = top.get("paginatedResultSet", {})
    total_pages = int(pagination.get("totalNumPages", 1))
    print(f"Page {page}/{total_pages} — {len(all_players)} players so far")
    if page >= total_pages:
        break
    page += 1

df = pd.DataFrame(all_players)
df = df[df["fpts_2025"] > 0]

print(f"\nTotal players with scores: {len(df)}")
print("\n=== FPts by Position (top positions) ===")
pos_stats = df.groupby("position").agg(
    count=("fpts_2025","count"),
    avg_fpts=("fpts_2025","mean"),
    median_fpts=("fpts_2025","median"),
    avg_fpg=("fpg_2025","mean"),
    top_fpts=("fpts_2025","max"),
).sort_values("avg_fpts", ascending=False)
print(pos_stats.round(1).to_string())

print("\n=== Top 20 players by FPts ===")
print(df.nlargest(20,"fpts_2025")[["name","position","fpts_2025","fpg_2025"]].to_string())

print("\n=== SP vs Hitter comparison ===")
sp = df[df["position"].str.contains("SP", na=False)]
hitters = df[~df["position"].str.contains("SP|RP", na=False)]
print(f"SP avg FPts: {sp['fpts_2025'].mean():.1f}, avg FP/G: {sp['fpg_2025'].mean():.1f}")
print(f"Hitter avg FPts: {hitters['fpts_2025'].mean():.1f}, avg FP/G: {hitters['fpg_2025'].mean():.1f}")
print(f"SP top 10 avg: {sp.nlargest(10,'fpts_2025')['fpts_2025'].mean():.1f}")
print(f"Hitter top 10 avg: {hitters.nlargest(10,'fpts_2025')['fpts_2025'].mean():.1f}")
