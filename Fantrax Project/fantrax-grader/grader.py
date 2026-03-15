"""
Player grading system — dynasty + Savant + league context aware.

Grade pipeline:
  1. dynasty_score = fantasy_pts * age_multiplier
  2. value_score = dynasty_score * scarcity_multiplier (SP premium)
  3. z-score within position GROUP (SP vs SP, OF vs OF etc.)
  4. Blend with Savant percentile score (60/40)
  5. Scale to 0-100 → A+ through F
"""
import pandas as pd
from league_context import get_position_group, get_scarcity_multiplier

GRADE_THRESHOLDS = [
    (90, "A+"), (85, "A"), (80, "A-"),
    (75, "B+"), (70, "B"), (65, "B-"),
    (55, "C+"), (50, "C"), (45, "C-"),
    (35, "D+"), (30, "D"), (0,  "F"),
]


def _letter_grade(score_0_100: float) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score_0_100 >= threshold:
            return grade
    return "F"


def grade_players(rosters_df: pd.DataFrame, savant_df: pd.DataFrame = None) -> pd.DataFrame:
    players = rosters_df.copy()
    players["dynasty_score"] = pd.to_numeric(
        players["dynasty_score"], errors="coerce"
    ).fillna(0)

    players["scarcity_mult"] = players["position"].apply(get_scarcity_multiplier)
    players["value_score"] = (players["dynasty_score"] * players["scarcity_mult"]).round(1)

    players["pos_group"] = players["position"].apply(get_position_group)

    players["dynasty_pct"] = (
        players.groupby("pos_group")["value_score"].transform(
            lambda x: ((x - x.mean()) / x.std()).clip(-3, 3) if x.std() > 0 else 0
        )
        .add(3).div(6).mul(100).round(1)
    )

    # Accept pre-loaded savant data or fall back to fetching
    if savant_df is None:
        from savant import get_all_savant_scores
        savant_df = get_all_savant_scores()

    savant = savant_df if savant_df is not None else pd.DataFrame()

    if not savant.empty:
        players = players.merge(
            savant[["name", "savant_score"] +
                   [c for c in savant.columns if c in
                    ["est_woba", "barrel_batted_rate", "sprint_speed",
                     "outs_above_average", "xera", "era"]]],
            on="name", how="left"
        )
        has_savant = players["savant_score"].notna()
        players["grade_pct"] = players["dynasty_pct"].copy()
        players.loc[has_savant, "grade_pct"] = (
            players.loc[has_savant, "dynasty_pct"] * 0.80 +
            players.loc[has_savant, "savant_score"] * 0.20
        ).round(1)
    else:
        players["savant_score"] = None
        players["grade_pct"] = players["dynasty_pct"]

    players["grade"] = players["grade_pct"].apply(_letter_grade)

    base_cols = ["name", "position", "pos_group", "team_name", "slot",
                 "age", "score", "ppg", "age_multiplier",
                 "dynasty_score", "scarcity_mult", "value_score",
                 "savant_score", "grade_pct", "grade"]
    extra_savant = [c for c in ["est_woba", "barrel_batted_rate",
                                "sprint_speed", "outs_above_average",
                                "xera", "era"] if c in players.columns]

    return players[base_cols + extra_savant].sort_values(
        "grade_pct", ascending=False
    ).reset_index(drop=True)


def rank_players(graded_df: pd.DataFrame, position: str | None = None) -> pd.DataFrame:
    df = graded_df.copy()
    if position:
        df = df[df["position"] == position]
    df = df.reset_index(drop=True)
    df.index += 1
    df.index.name = "rank"
    return df.reset_index()
