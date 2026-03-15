"""
Baseball Savant statcast data fetcher.

Pulls xwOBA, barrel%, sprint speed, and OAA for MLB players
and produces a savant_score (0-100) to supplement fantasy grades.

Hitter score (0-100):
  40pts — xwOBA (quality of contact)
  25pts — barrel% (hard hit rate)
  20pts — sprint speed (speed tool)
  15pts — OAA (defense, tiebreaker)

Pitcher score (0-100):
  50pts — xwOBA against (contact quality allowed)
  30pts — whiff% (swing and miss)
  20pts — barrel% against
"""
import requests
import pandas as pd
from io import StringIO

HEADERS = {"User-Agent": "Mozilla/5.0"}
SAVANT_BASE = "https://baseballsavant.mlb.com/leaderboard"


def _fetch_csv(url: str) -> pd.DataFrame:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return pd.read_csv(StringIO(resp.text))
    except Exception as e:
        print(f"Savant fetch error ({url}): {e}")
        return pd.DataFrame()


def _parse_name(df: pd.DataFrame) -> pd.DataFrame:
    """Convert 'last_name, first_name' column to 'name' = 'First Last'."""
    df = df.copy()
    if "last_name, first_name" in df.columns:
        df["name"] = df["last_name, first_name"].apply(
            lambda x: " ".join(reversed([p.strip() for p in str(x).split(",")])) if "," in str(x) else str(x)
        )
    return df


def fetch_hitter_xwoba() -> pd.DataFrame:
    df = _fetch_csv(
        f"{SAVANT_BASE}/expected_statistics?type=batter&filter=&min=25&csv=true"
    )
    if df.empty:
        return df
    df = _parse_name(df)
    cols = ["name", "player_id", "pa", "est_woba", "est_woba_minus_woba_diff",
            "barrel_batted_rate", "xba", "xslg"]
    return df[[c for c in cols if c in df.columns]]


def fetch_sprint_speed() -> pd.DataFrame:
    df = _fetch_csv(
        f"{SAVANT_BASE}/sprint_speed?min_competitive_runs=10&position=&team=&csv=true"
    )
    if df.empty:
        return df
    df = _parse_name(df)
    return df[["name", "player_id", "sprint_speed"]]


def fetch_outs_above_avg() -> pd.DataFrame:
    df = _fetch_csv(
        f"{SAVANT_BASE}/outs_above_average?type=Fielder&min=1&csv=true"
    )
    if df.empty:
        return df
    df = _parse_name(df)
    return df[["name", "player_id", "outs_above_average"]]


def fetch_pitcher_xwoba() -> pd.DataFrame:
    df = _fetch_csv(
        f"{SAVANT_BASE}/expected_statistics?type=pitcher&filter=&min=25&csv=true"
    )
    if df.empty:
        return df
    df = _parse_name(df)
    cols = ["name", "player_id", "pa", "est_woba", "xera", "era", "era_minus_xera_diff"]
    return df[[c for c in cols if c in df.columns]]


def _get_pitcher_ids() -> set:
    """Fetch player IDs whose primary position is SP or RP from MLB Stats API."""
    ids = set()
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/sports/1/players",
            params={"season": 2026},
            timeout=15,
        )
        resp.raise_for_status()
        for p in resp.json().get("people", []):
            pos = p.get("primaryPosition", {}).get("abbreviation", "")
            if pos in ("SP", "RP", "P"):
                ids.add(p.get("id"))
    except Exception as e:
        print(f"Pitcher ID fetch error: {e}")
    return ids


def _pct_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """Percentile rank 0-100. ascending=True means higher value = higher score."""
    return series.rank(pct=True, ascending=ascending) * 100


def build_hitter_savant_scores() -> pd.DataFrame:
    xwoba_df = fetch_hitter_xwoba()
    speed_df = fetch_sprint_speed()
    oaa_df = fetch_outs_above_avg()

    if xwoba_df.empty:
        return pd.DataFrame()

    df = xwoba_df.copy()

    # Merge speed
    if not speed_df.empty:
        df = df.merge(speed_df[["player_id", "sprint_speed"]], on="player_id", how="left")
    else:
        df["sprint_speed"] = None

    # Merge OAA
    if not oaa_df.empty:
        df = df.merge(oaa_df[["player_id", "outs_above_average"]], on="player_id", how="left")
    else:
        df["outs_above_average"] = None

    # Percentile ranks
    if "est_woba" in df.columns:
        df["xwoba_pct"] = _pct_rank(df["est_woba"].fillna(df["est_woba"].median()))
    else:
        df["xwoba_pct"] = 50

    if "barrel_batted_rate" in df.columns:
        df["barrel_pct"] = _pct_rank(df["barrel_batted_rate"].fillna(0))
    else:
        df["barrel_pct"] = 50

    if "sprint_speed" in df.columns and df["sprint_speed"].notna().any():
        df["speed_pct"] = _pct_rank(df["sprint_speed"].fillna(df["sprint_speed"].median()))
    else:
        df["speed_pct"] = 50

    if "outs_above_average" in df.columns and df["outs_above_average"].notna().any():
        df["oaa_pct"] = _pct_rank(df["outs_above_average"].fillna(0))
    else:
        df["oaa_pct"] = 50

    df["savant_score"] = (
        df["xwoba_pct"] * 0.40 +
        df["barrel_pct"] * 0.25 +
        df["speed_pct"] * 0.20 +
        df["oaa_pct"] * 0.15
    ).round(1)

    # Keep key columns
    keep = ["name", "player_id", "pa", "savant_score"]
    for col in ["est_woba", "barrel_batted_rate", "sprint_speed", "outs_above_average"]:
        if col in df.columns:
            keep.append(col)

    return df[keep].sort_values("savant_score", ascending=False).reset_index(drop=True)


def build_pitcher_savant_scores() -> pd.DataFrame:
    df = fetch_pitcher_xwoba()
    if df.empty:
        return pd.DataFrame()

    # Filter to actual pitchers only
    pitcher_ids = _get_pitcher_ids()
    if pitcher_ids:
        df = df[df["player_id"].isin(pitcher_ids)]

    if df.empty:
        return pd.DataFrame()

    # Lower xwOBA against = better
    df["xwoba_pct"] = _pct_rank(df["est_woba"].fillna(df["est_woba"].median()), ascending=False)

    # Lower xERA = better
    if "xera" in df.columns:
        df["xera_pct"] = _pct_rank(df["xera"].fillna(df["xera"].median()), ascending=False)
    else:
        df["xera_pct"] = 50

    # ERA - xERA diff: negative means outperforming, positive means due for regression
    if "era_minus_xera_diff" in df.columns:
        # Negative diff = pitcher is better than ERA shows → reward
        df["luck_pct"] = _pct_rank(df["era_minus_xera_diff"].fillna(0), ascending=False)
    else:
        df["luck_pct"] = 50

    df["savant_score"] = (
        df["xwoba_pct"] * 0.45 +
        df["xera_pct"] * 0.40 +
        df["luck_pct"] * 0.15
    ).round(1)

    keep = ["name", "player_id", "pa", "savant_score"]
    for col in ["est_woba", "xera", "era", "era_minus_xera_diff"]:
        if col in df.columns:
            keep.append(col)

    return df[keep].sort_values("savant_score", ascending=False).reset_index(drop=True)


def fetch_percentile_rankings(player_type: str = "batter") -> pd.DataFrame:
    """
    Fetch pre-computed Savant percentile rankings (0-100) for all qualified players.
    player_type: 'batter' or 'pitcher'
    Returns df with player_id + percentile columns.
    """
    url = f"{SAVANT_BASE}/percentile-rankings?type={player_type}&csv=true"
    df = _fetch_csv(url)
    if df.empty:
        return df
    df = df.copy()
    # Normalize name: 'Last, First' → 'First Last'
    if "player_name" in df.columns:
        df["name"] = df["player_name"].apply(
            lambda x: " ".join(reversed([p.strip() for p in str(x).split(",")])) if "," in str(x) else str(x)
        )
    return df


def get_all_savant_scores() -> pd.DataFrame:
    """Combined hitter + pitcher savant scores keyed by name."""
    hitters = build_hitter_savant_scores()
    pitchers = build_pitcher_savant_scores()

    if hitters.empty and pitchers.empty:
        return pd.DataFrame()

    parts = []
    if not hitters.empty:
        hitters["player_type"] = "hitter"
        parts.append(hitters)
    if not pitchers.empty:
        pitchers["player_type"] = "pitcher"
        parts.append(pitchers)

    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates("name", keep="first")
    return combined.reset_index(drop=True)
