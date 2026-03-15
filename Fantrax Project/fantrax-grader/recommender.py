"""
Trade recommender — dynasty + Savant aware.

Philosophy: every proposal should make BOTH teams better off.
  - You fill a weak position, they fill one of theirs.
  - Value must be balanced (within tight gap).
  - Net gain is near zero — fairness, not exploitation.

Trade types:
  1. 1-for-1: swap positional needs
  2. 2-for-1: give two depth pieces, receive one elite
  3. 1-for-2: sell high, receive two younger pieces
"""
import pandas as pd
from itertools import combinations

MAX_1FOR1_GAP   = 12   # max grade_pct gap for a fair 1-for-1
MAX_MULTI_GAP   = 15   # max combined value gap for multi-player trades
MIN_NET         = -10  # allow up to 10-pt differential
MAX_NET         = 10
MIN_PLAYER_GRADE = 30  # no scrubs
MAX_PROPOSALS   = 10

# Intent → (min_net, max_net, prefer_younger_in, prefer_older_in, prefer_more_in, prefer_fewer_in)
# min/max net = from MY perspective (positive = I gain value)
INTENT_PROFILES = {
    "🔨 Rebuild":    {"min_net": -10, "max_net":  3, "younger_in": True,  "older_in": False, "more_in": True,  "fewer_in": False},
    "🏆 Win Now":    {"min_net":  -3, "max_net": 10, "younger_in": False, "older_in": True,  "more_in": False, "fewer_in": True},
    "📈 Value Grab": {"min_net":   2, "max_net": 10, "younger_in": False, "older_in": False, "more_in": False, "fewer_in": False},
    "📦 Depth Add":  {"min_net": -10, "max_net":  5, "younger_in": False, "older_in": False, "more_in": True,  "fewer_in": False},
    "⭐ Consolidate":{"min_net":  -5, "max_net": 10, "younger_in": False, "older_in": False, "more_in": False, "fewer_in": True},
    "🔄 Lateral":    {"min_net":  -5, "max_net":  5, "younger_in": False, "older_in": False, "more_in": False, "fewer_in": False},
    "🎲 Random":     {"min_net": -10, "max_net": 10, "younger_in": False, "older_in": False, "more_in": False, "fewer_in": False},
}

# Search depth limits — keep combos fast
_N1 = 12   # 1-for-1: top N players per side
_N2 = 8    # 2-for-X: top N for pair combos
_N3 = 6    # 3-for-X: top N for triple combos


def _pos_col(df):
    return "pos_group" if "pos_group" in df.columns else "position"


def _team_pos_avg(graded_df, team):
    col = _pos_col(graded_df)
    return graded_df[graded_df["team_name"] == team].groupby(col)["grade_pct"].mean()


def _league_pos_avg(graded_df):
    col = _pos_col(graded_df)
    return graded_df.groupby(col)["grade_pct"].mean()


def _weak_positions(graded_df, team):
    league = _league_pos_avg(graded_df)
    mine   = _team_pos_avg(graded_df, team)
    return [p for p in mine.index if p in league.index and mine[p] < league[p]]


def _strong_positions(graded_df, team):
    league = _league_pos_avg(graded_df)
    mine   = _team_pos_avg(graded_df, team)
    return [p for p in mine.index if p in league.index and mine[p] > league[p]]


def _tradeable(graded_df, team, exclude_top_n=2):
    """Players eligible to be traded (skip their top N untouchables)."""
    return (
        graded_df[(graded_df["team_name"] == team) & (graded_df["grade_pct"] >= MIN_PLAYER_GRADE)]
        .sort_values("grade_pct", ascending=False)
        .iloc[exclude_top_n:]
        .reset_index(drop=True)
    )


def _targetable(graded_df, team):
    """Players we can ask for (skip their single best player)."""
    return (
        graded_df[(graded_df["team_name"] == team) & (graded_df["grade_pct"] >= MIN_PLAYER_GRADE)]
        .sort_values("grade_pct", ascending=False)
        .iloc[1:]
        .reset_index(drop=True)
    )


def _player_dict(row):
    return {
        "name":       row["name"],
        "position":   row["position"],
        "pos_group":  row.get("pos_group", ""),
        "team_name":  row["team_name"],
        "grade_pct":  row["grade_pct"],
        "grade":      row["grade"],
        "age":        row.get("age", "?"),
        "savant_score": row.get("savant_score"),
        "value_score":  row.get("value_score", row["grade_pct"]),
    }


def _trade_summary(give, receive):
    give_val = sum(p["grade_pct"] for p in give)
    recv_val = sum(p["grade_pct"] for p in receive)

    # ── Trade intent classification ───────────────────────────────────────────
    give_ages = [p.get("age") or 27 for p in give]
    recv_ages = [p.get("age") or 27 for p in receive]
    try:
        give_avg_age = sum(float(a) for a in give_ages) / len(give_ages)
        recv_avg_age = sum(float(a) for a in recv_ages) / len(recv_ages)
    except Exception:
        give_avg_age = recv_avg_age = 27.0

    age_delta = recv_avg_age - give_avg_age   # positive = getting older
    val_delta = recv_val - give_val            # positive = gaining value

    if age_delta <= -2 and val_delta >= -5:
        intent = "🔨 Rebuild"
        intent_tip = "Getting younger — trading present for future"
    elif age_delta >= 2 and val_delta >= 0:
        intent = "🏆 Win Now"
        intent_tip = "Getting older/better — pushing for a title"
    elif val_delta >= 3:
        intent = "📈 Value Grab"
        intent_tip = "Straight-up value upgrade"
    elif len(receive) > len(give):
        intent = "📦 Depth Add"
        intent_tip = "Trading one good piece for multiple contributors"
    elif len(give) > len(receive):
        intent = "⭐ Consolidate"
        intent_tip = "Packaging depth to land a star"
    else:
        intent = "🔄 Lateral"
        intent_tip = "Even swap — positional fit is the win"

    return {
        "give":         give,
        "receive":      receive,
        "give_total":   round(give_val, 1),
        "receive_total": round(recv_val, 1),
        "net_gain":     round(recv_val - give_val, 1),
        "other_team":   receive[0]["team_name"],
        "trade_type":   f"{len(give)}-for-{len(receive)}",
        "intent":       intent,
        "intent_tip":   intent_tip,
    }


def _mutually_beneficial(graded_df, my_team, other_team, give_rows, recv_rows) -> bool:
    """
    Returns True if the trade plausibly helps both teams.
    Uses the original DataFrame rows (pd.Series) so pos_group lookup is reliable.
    Falls back to True if positional data is missing — value balance is the main guard.
    """
    col = _pos_col(graded_df)
    my_weak    = set(_weak_positions(graded_df, my_team))
    my_strong  = set(_strong_positions(graded_df, my_team))
    their_weak = set(_weak_positions(graded_df, other_team))
    their_strong = set(_strong_positions(graded_df, other_team))

    # give_rows / recv_rows are pd.Series from iterrows()
    def pos(row):
        return row.get(col, row.get("pos_group", row.get("position", "")))

    give_positions = [pos(r) for r in give_rows]
    recv_positions = [pos(r) for r in recv_rows]

    # If we can't determine positions, allow the trade (value gap is the guard)
    if not any(give_positions) and not any(recv_positions):
        return True

    i_benefit = any(p in my_weak for p in recv_positions) or \
                any(p in my_strong for p in give_positions)
    they_benefit = any(p in their_weak for p in give_positions) or \
                   any(p in their_strong for p in recv_positions)

    # At least one side must clearly benefit; don't require both to have perfect positional fit
    return i_benefit or they_benefit


def recommend_trades(graded_df: pd.DataFrame, my_team: str, max_proposals: int = MAX_PROPOSALS, trade_intent: str = "🎲 Random") -> list[dict]:
    profile = INTENT_PROFILES.get(trade_intent, INTENT_PROFILES["🎲 Random"])
    min_net = profile["min_net"]
    max_net = profile["max_net"]
    want_younger_in  = profile["younger_in"]
    want_older_in    = profile["older_in"]
    want_more_in     = profile["more_in"]
    want_fewer_in    = profile["fewer_in"]

    proposals = []
    other_teams  = [t for t in graded_df["team_name"].unique() if t != my_team]
    my_tradeable = _tradeable(graded_df, my_team)

    def _check_and_add(give_rows, recv_rows, other_team):
        give_val = sum(r["grade_pct"] for r in give_rows)
        recv_val = sum(r["grade_pct"] for r in recv_rows)
        gap = abs(give_val - recv_val)
        net = recv_val - give_val

        if gap > MAX_MULTI_GAP or not (min_net <= net <= max_net):
            return

        # Intent-specific structural filters
        give_ages = [float(r.get("age") or 27) for r in give_rows]
        recv_ages = [float(r.get("age") or 27) for r in recv_rows]
        give_avg_age = sum(give_ages) / len(give_ages)
        recv_avg_age = sum(recv_ages) / len(recv_ages)

        if want_younger_in and recv_avg_age >= give_avg_age:
            return
        if want_older_in and recv_avg_age <= give_avg_age - 1:
            return
        if want_more_in and len(recv_rows) <= len(give_rows):
            return
        if want_fewer_in and len(recv_rows) >= len(give_rows):
            return

        if _mutually_beneficial(graded_df, my_team, other_team, give_rows, recv_rows):
            proposals.append(_trade_summary(
                [_player_dict(r) for r in give_rows],
                [_player_dict(r) for r in recv_rows],
            ))

    for other_team in other_teams:
        their_targetable = _targetable(graded_df, other_team)
        their_tradeable  = _tradeable(graded_df, other_team)

        # Slice to search limits
        my_1  = my_tradeable.head(_N1)
        my_2  = my_tradeable.head(_N2)
        my_3  = my_tradeable.head(_N3)
        tgt_1 = their_targetable.head(_N1)
        trd_2 = their_tradeable.head(_N2)
        trd_3 = their_tradeable.head(_N3)

        # ── 1-for-1 ──────────────────────────────────────────────────────────
        for _, rv in tgt_1.iterrows():
            for _, gv in my_1.iterrows():
                if abs(rv["grade_pct"] - gv["grade_pct"]) <= MAX_1FOR1_GAP:
                    _check_and_add([gv], [rv], other_team)

        # ── 2-for-1 ──────────────────────────────────────────────────────────
        for ti in range(len(tgt_1)):
            rv = tgt_1.iloc[ti]
            for gi, gj in combinations(range(len(my_2)), 2):
                _check_and_add([my_2.iloc[gi], my_2.iloc[gj]], [rv], other_team)

        # ── 1-for-2 ──────────────────────────────────────────────────────────
        for gi in range(len(my_2)):
            gv = my_2.iloc[gi]
            for ri, rj in combinations(range(len(trd_2)), 2):
                _check_and_add([gv], [trd_2.iloc[ri], trd_2.iloc[rj]], other_team)

        # ── 2-for-2 ──────────────────────────────────────────────────────────
        for gi, gj in combinations(range(len(my_2)), 2):
            for ri, rj in combinations(range(len(trd_2)), 2):
                _check_and_add(
                    [my_2.iloc[gi], my_2.iloc[gj]],
                    [trd_2.iloc[ri], trd_2.iloc[rj]],
                    other_team)

        # ── 3-for-2 ──────────────────────────────────────────────────────────
        for gi, gj, gk in combinations(range(len(my_3)), 3):
            for ri, rj in combinations(range(len(trd_3)), 2):
                _check_and_add(
                    [my_3.iloc[gi], my_3.iloc[gj], my_3.iloc[gk]],
                    [trd_3.iloc[ri], trd_3.iloc[rj]],
                    other_team)

        # ── 2-for-3 ──────────────────────────────────────────────────────────
        for gi, gj in combinations(range(len(my_3)), 2):
            for ri, rj, rk in combinations(range(len(trd_3)), 3):
                _check_and_add(
                    [my_3.iloc[gi], my_3.iloc[gj]],
                    [trd_3.iloc[ri], trd_3.iloc[rj], trd_3.iloc[rk]],
                    other_team)

    # Deduplicate, sort by most balanced (closest net to 0) first
    seen, unique = set(), []
    for p in sorted(proposals, key=lambda x: abs(x["net_gain"])):
        key = (
            tuple(sorted(g["name"] for g in p["give"])),
            tuple(sorted(r["name"] for r in p["receive"])),
        )
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Random: shuffle so repeated clicks give variety
    if trade_intent == "🎲 Random":
        import random
        random.shuffle(unique)

    return unique[:max_proposals]
