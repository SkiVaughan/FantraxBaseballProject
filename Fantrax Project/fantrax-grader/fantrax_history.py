"""
Pulls multi-year Fantrax FPts + projections for all players.
Returns a DataFrame with columns:
  name, fpts_2024, fpts_2025, fpts_proj, fpg_proj, dynasty_rank_score
"""
import pandas as pd

FANTRAX_API = "https://www.fantrax.com/fxpa/req"

SEASONS = {
    "fpts_2024": "SEASON_143_YEAR_TO_DATE",
    "fpts_2025": "SEASON_145_YEAR_TO_DATE",
    "fpts_proj": "PROJECTION_0_147_SEASON",
}


def _fetch_all_pages(session, league_id: str, season_code: str) -> list[dict]:
    rows = []
    page = 1
    while True:
        payload = {
            "msgs": [{
                "method": "getPlayerStats",
                "data": {
                    "leagueId": league_id,
                    "reload": "1",
                    "statusOrTeamFilter": "ALL",
                    "pageNumber": str(page),
                    "maxResultsPerPage": "500",
                    "view": "STATS",
                    "sortType": "SCORE",
                    "seasonOrProjection": season_code,
                },
            }]
        }
        try:
            resp = session.post(
                FANTRAX_API,
                params={"leagueId": league_id},
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            top = data["responses"][0]["data"]
        except Exception as e:
            print(f"  Error page {page}: {e}")
            break

        for row in top.get("statsTable", []):
            scorer = row["scorer"]
            cells = row["cells"]
            try:
                fpts = float(cells[4]["content"]) if cells[4]["content"] else 0
                fpg  = float(cells[5]["content"]) if cells[5]["content"] else 0
            except (IndexError, ValueError):
                fpts, fpg = 0, 0
            rows.append({
                "name": scorer["name"],
                "fpts": fpts,
                "fpg": fpg,
            })

        pagination = top.get("paginatedResultSet", {})
        total_pages = int(pagination.get("totalNumPages", 1))
        if page >= total_pages:
            break
        page += 1

    return rows


def fetch_all_seasons(session, league_id: str) -> pd.DataFrame:
    """
    Fetches 2024, 2025 actuals + 2026 projections, then blends in dynasty rankings.
    Returns wide DataFrame keyed by player name.
    """
    from dynasty_rankings import fetch_dynasty_rankings, lookup_dynasty_score

    combined = None

    for col_name, season_code in SEASONS.items():
        print(f"  Fetching {col_name}...")
        rows = _fetch_all_pages(session, league_id, season_code)
        df = pd.DataFrame(rows)
        if df.empty:
            continue

        # For projections also keep fpg
        if col_name == "fpts_proj":
            df = df.rename(columns={"fpts": "fpts_proj", "fpg": "fpg_proj"})
            df = df[["name", "fpts_proj", "fpg_proj"]]
        else:
            df = df.rename(columns={"fpts": col_name})
            df = df[["name", col_name]]

        # Keep max per player (in case of duplicates)
        df = df.groupby("name").max().reset_index()

        if combined is None:
            combined = df
        else:
            combined = combined.merge(df, on="name", how="outer")

    if combined is None:
        return pd.DataFrame()

    # Fill missing years with 0
    for col in ["fpts_2024", "fpts_2025", "fpts_proj", "fpg_proj"]:
        if col not in combined.columns:
            combined[col] = 0
        combined[col] = combined[col].fillna(0)

    # Attach dynasty rank scores (0-100) for each player
    print("  Attaching dynasty rankings...")
    dynasty_scores = fetch_dynasty_rankings()
    combined["dynasty_rank_score"] = combined["name"].apply(
        lambda n: lookup_dynasty_score(n, dynasty_scores)
    )

    return combined.reset_index(drop=True)


def compute_weighted_fpts(
    df: pd.DataFrame,
    w_proj: float = 0.35,
    w_2025: float = 0.25,
    w_2024: float = 0.20,
    w_dynasty: float = 0.10,
    w_trend: float = 0.10,
) -> pd.DataFrame:
    """
    Computes a weighted fantasy score. Weights are configurable so the
    Streamlit UI can pass slider values directly.

    Default weights:
      35% projection, 25% 2025, 20% 2024, 10% dynasty rankings, 10% trend
    """
    df = df.copy()

    df["trend"] = (
        (df["fpts_2025"] - df["fpts_2024"]).clip(lower=0) * 0.5
    )

    dynasty_rank_score = df.get("dynasty_rank_score", pd.Series(50.0, index=df.index))
    dynasty_rank_score = dynasty_rank_score.fillna(50.0)
    dynasty_fpts_equiv = dynasty_rank_score * 3.0  # scale 0-100 → 0-300

    df["weighted_fpts"] = (
        df["fpts_proj"]    * w_proj +
        df["fpts_2025"]    * w_2025 +
        df["fpts_2024"]    * w_2024 +
        dynasty_fpts_equiv * w_dynasty +
        df["trend"]        * w_trend
    ).round(1)

    return df
