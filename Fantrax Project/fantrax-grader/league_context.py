"""
League-specific scoring context derived from 2025 season analysis.

Key findings:
  - SP avg FP/G: 9.2  vs hitter avg FP/G: 1.4  (6.5x multiplier)
  - RP avg FP/G: 2.7
  - Top SP avg season: 569 pts, top hitter avg: 512 pts
  - Pitching is the scarce premium resource in this league

Position tiers used for grading normalization and trade valuation.
Players are graded within their position group so a C grades against
other Cs, SPs against other SPs etc.

POSITION_FPG_BASELINE: median FP/G for a "starter-quality" player
at each position. Used to compute replacement-level value.
"""

# Median FP/G for a rostered-quality player at each position
# Derived from 2025 Fantrax data (top ~50% of rostered players)
POSITION_FPG_BASELINE = {
    "SP":  9.2,
    "RP":  2.7,
    "C":   1.2,
    "1B":  1.6,
    "2B":  1.4,
    "3B":  1.5,
    "SS":  1.8,
    "OF":  1.4,
    "UT":  1.8,
    "P":   9.2,   # two-way (Ohtani-type)
}

# How many roster spots typically exist per position
# Affects scarcity premium
POSITION_SCARCITY = {
    "SP":  1.8,   # scarce — high premium
    "RP":  1.2,
    "C":   1.3,   # scarce positionally
    "1B":  1.0,
    "2B":  1.0,
    "3B":  1.0,
    "SS":  1.1,
    "OF":  1.0,
    "UT":  1.0,
    "P":   1.8,
}

# Position groups for z-score grading
# Players are only compared within their group
POSITION_GROUPS = {
    "SP": "pitcher",
    "RP": "pitcher",
    "P":  "pitcher",
    "C":  "catcher",
    "1B": "corner_infield",
    "3B": "corner_infield",
    "2B": "middle_infield",
    "SS": "middle_infield",
    "OF": "outfield",
    "UT": "utility",
}


def get_position_group(pos_str: str) -> str:
    """Map a Fantrax position string to a grading group."""
    if not pos_str:
        return "other"
    # Handle multi-position strings like "2B,SS"
    primary = pos_str.split(",")[0].strip()
    return POSITION_GROUPS.get(primary, "other")


def get_scarcity_multiplier(pos_str: str) -> float:
    """Return scarcity premium for a position."""
    if not pos_str:
        return 1.0
    primary = pos_str.split(",")[0].strip()
    return POSITION_SCARCITY.get(primary, 1.0)


def get_fpg_baseline(pos_str: str) -> float:
    """Return the FP/G baseline for a position."""
    if not pos_str:
        return 1.4
    primary = pos_str.split(",")[0].strip()
    return POSITION_FPG_BASELINE.get(primary, 1.4)
