"""
Dynasty value calculation.

dynasty_score = weighted_fpts * age_multiplier * scarcity_multiplier

Age multiplier is performance-aware for players 28+:
  - Elite vets (top-tier weighted_fpts) age more gracefully — less penalty
  - Mid/low tier aging players get a steeper decline curve
  - Under 28: flat curve, same for everyone (upside is upside)

Tiers for 28+ penalty adjustment (based on weighted_fpts percentile):
  Elite  (top 15%): age penalty reduced by 40%
  Good   (top 40%): age penalty reduced by 20%
  Mid    (mid 30%): base penalty
  Low    (bot 30%): age penalty increased by 25%
"""
import pandas as pd

# Base age multipliers (27 = 1.0 baseline)
_BASE_AGE = {
    21: 1.35, 22: 1.28, 23: 1.20, 24: 1.12,
    25: 1.06, 26: 1.02, 27: 1.00, 28: 0.95,
    29: 0.88, 30: 0.80, 31: 0.70, 32: 0.60,
    33: 0.50, 34: 0.42,
}
_BASE_FLOOR = 0.35  # absolute floor for any age >= 35


def _base_age_mult(age: int) -> float:
    if age <= 21:
        return 1.35
    if age >= 35:
        return _BASE_FLOOR
    return _BASE_AGE.get(age, 1.0)


def _performance_aware_age_mult(age: int, weighted_fpts: float,
                                 elite_thresh: float, good_thresh: float,
                                 low_thresh: float) -> float:
    """
    For players 28+, adjust the age penalty based on how elite they are.
    Players under 28 get the flat base multiplier — youth upside is universal.
    """
    base = _base_age_mult(age)

    if age < 28:
        return base

    # How much below 1.0 is the penalty?
    penalty = 1.0 - base  # positive number, e.g. age 33 base=0.50 → penalty=0.50

    if weighted_fpts >= elite_thresh:
        # Elite vet: reduce penalty by 40% (ages much better)
        adjusted = 1.0 - penalty * 0.60
    elif weighted_fpts >= good_thresh:
        # Good vet: reduce penalty by 20%
        adjusted = 1.0 - penalty * 0.80
    elif weighted_fpts <= low_thresh:
        # Declining mid-tier: increase penalty by 25%
        adjusted = 1.0 - penalty * 1.25
    else:
        adjusted = base

    return round(max(_BASE_FLOOR, min(1.10, adjusted)), 3)


def fetch_player_ages(names: list[str]) -> dict[str, int]:
    """Looks up ages from the MLB Stats API. Result is module-level cached."""
    import requests

    if not hasattr(fetch_player_ages, "_cache"):
        fetch_player_ages._cache = {}
        fetch_player_ages._lookup = {}  # normalized name -> age

    ages = fetch_player_ages._cache
    lookup = fetch_player_ages._lookup

    if lookup:  # already fetched
        for name in names:
            if name not in ages:
                # try fuzzy: last name match
                key = name.lower().strip()
                if key in lookup:
                    ages[name] = lookup[key]
                else:
                    # last name only fallback
                    last = key.split()[-1] if key.split() else key
                    for k, v in lookup.items():
                        if k.split()[-1] == last and k.split()[0][0] == key.split()[0][0]:
                            ages[name] = v
                            break
        return {n: ages[n] for n in names if n in ages}

    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/sports/1/players",
            params={"season": 2026}, timeout=15,
        )
        resp.raise_for_status()
        for p in resp.json().get("people", []):
            lookup[p["fullName"].lower()] = p.get("currentAge", 0)
    except Exception as e:
        print(f"Age fetch error: {e}")

    for name in names:
        key = name.lower().strip()
        if key in lookup:
            ages[name] = lookup[key]
        else:
            last = key.split()[-1] if key.split() else key
            for k, v in lookup.items():
                if k.split()[-1] == last and k.split()[0][0] == key.split()[0][0]:
                    ages[name] = v
                    break

    return {n: ages[n] for n in names if n in ages}


def apply_dynasty_value(rosters_df: pd.DataFrame, history_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Merges multi-year history into roster data and computes dynasty_score.
    Age multiplier is performance-aware for players 28+.
    """
    from league_context import get_scarcity_multiplier

    df = rosters_df.copy()

    # Merge multi-year history
    if history_df is not None and not history_df.empty:
        merge_cols = ["name", "fpts_2024", "fpts_2025",
                      "fpts_proj", "fpg_proj", "weighted_fpts"]
        if "dynasty_rank_score" in history_df.columns:
            merge_cols.append("dynasty_rank_score")
        df = df.merge(history_df[merge_cols], on="name", how="left")
        df["weighted_fpts"] = df["weighted_fpts"].fillna(
            pd.to_numeric(df["score"], errors="coerce").fillna(0)
        )
    else:
        df["weighted_fpts"] = pd.to_numeric(df["score"], errors="coerce").fillna(0)
        df["fpts_2024"] = 0
        df["fpts_2025"] = df["weighted_fpts"]
        df["fpts_proj"] = df["weighted_fpts"]
        df["fpg_proj"] = pd.to_numeric(df.get("ppg", 0), errors="coerce").fillna(0)
        df["dynasty_rank_score"] = 50.0

    # Ages
    names = df["name"].dropna().unique().tolist()
    ages = fetch_player_ages(names)
    df["age"] = df["name"].map(ages)

    # Compute performance thresholds across the whole roster
    wfpts = pd.to_numeric(df["weighted_fpts"], errors="coerce").fillna(0)
    elite_thresh = float(wfpts.quantile(0.85))
    good_thresh  = float(wfpts.quantile(0.60))
    low_thresh   = float(wfpts.quantile(0.30))

    df["age_multiplier"] = df.apply(
        lambda row: _performance_aware_age_mult(
            age=int(row["age"]) if pd.notna(row["age"]) else 27,
            weighted_fpts=float(row["weighted_fpts"]) if pd.notna(row["weighted_fpts"]) else 0,
            elite_thresh=elite_thresh,
            good_thresh=good_thresh,
            low_thresh=low_thresh,
        ),
        axis=1,
    )

    # Scarcity
    df["scarcity_mult"] = df["position"].apply(get_scarcity_multiplier)

    # Final dynasty score
    df["dynasty_score"] = (
        df["weighted_fpts"] * df["age_multiplier"] * df["scarcity_mult"]
    ).round(1)

    return df
