"""
Prospect rankings + waiver wire availability checker.

Sources:
  1. MLB Pipeline (statsapi.mlb.com) — official prospect rankings
  2. MLB Stats API minor league player pool — for age/level/stats
  3. Fantrax /fxpa/req getAvailablePlayers — checks who is unclaimed

Rankings are combined into a consensus score, then filtered to
only show players available on your waiver wire.
"""
import requests
import pandas as pd

MLB_API = "https://statsapi.mlb.com/api/v1"
FANTRAX_API = "https://www.fantrax.com/fxpa/req"

# Minor league sport IDs in the MLB Stats API
MILB_SPORT_IDS = [11, 12, 13, 14, 16]  # AAA, AA, High-A, A, Rookie
SPORT_NAMES = {11: "AAA", 12: "AA", 13: "High-A", 14: "A", 16: "Rookie"}


# ── MLB Pipeline prospect rankings ───────────────────────────────────────────

def fetch_mlb_pipeline_rankings() -> pd.DataFrame:
    """
    Pulls the MLB Pipeline Top 100 prospect list via the stats API.
    Returns DataFrame with name, rank, position, org, age.
    """
    rows = []
    try:
        resp = requests.get(
            f"{MLB_API}/people",
            params={
                "sportId": 11,
                "season": 2026,
                "fields": "people,fullName,currentAge,primaryPosition,prospectRank,currentTeam",
            },
            timeout=15,
        )
        resp.raise_for_status()
        # Try the dedicated prospect endpoint
        prospect_resp = requests.get(
            "https://statsapi.mlb.com/api/v1/sports/1/players",
            params={"season": 2026, "gameType": "R"},
            timeout=15,
        )
    except Exception:
        pass

    # Use the prospect rankings endpoint
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/draft/prospects",
            params={"year": 2026},
            timeout=15,
        )
        if r.ok:
            for p in r.json().get("prospects", []):
                rows.append({
                    "name": p.get("person", {}).get("fullName", ""),
                    "pipeline_rank": p.get("rank", 999),
                    "position": p.get("primaryPosition", {}).get("abbreviation", ""),
                    "org": p.get("team", {}).get("abbreviation", ""),
                    "age": p.get("person", {}).get("currentAge"),
                    "source": "MLB Pipeline",
                })
    except Exception:
        pass

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["name", "pipeline_rank", "position", "org", "age", "source"]
    )


def fetch_milb_players() -> pd.DataFrame:
    """
    Fetches all active minor league players across AAA/AA/High-A/A/Rookie
    from the MLB Stats API with age, position, and level.
    """
    all_players = []
    for sport_id in MILB_SPORT_IDS:
        try:
            resp = requests.get(
                f"{MLB_API}/sports/{sport_id}/players",
                params={"season": 2026},
                timeout=20,
            )
            resp.raise_for_status()
            for p in resp.json().get("people", []):
                all_players.append({
                    "mlb_id": p.get("id"),
                    "name": p.get("fullName", ""),
                    "age": p.get("currentAge"),
                    "position": p.get("primaryPosition", {}).get("abbreviation", ""),
                    "level": SPORT_NAMES[sport_id],
                    "level_order": sport_id,  # lower = higher level
                    "org": p.get("currentTeam", {}).get("abbreviation", ""),
                    "birth_date": p.get("birthDate", ""),
                })
        except Exception:
            continue

    if not all_players:
        return pd.DataFrame()

    df = pd.DataFrame(all_players)
    # Keep highest level per player (they may appear in multiple)
    df = df.sort_values("level_order").drop_duplicates("name", keep="first")
    return df.reset_index(drop=True)


# ── Fantrax available players ─────────────────────────────────────────────────

def fetch_available_players(league_id: str, session: requests.Session) -> set[str]:
    """
    Calls Fantrax getPlayerStats with ALL_AVAILABLE filter.
    Returns a set of available player names.
    Paginates through all pages to get the full list.
    """
    available = set()
    try:
        page = 1
        while True:
            payload = {
                "msgs": [{
                    "method": "getPlayerStats",
                    "data": {
                        "leagueId": league_id,
                        "reload": "1",
                        "statusOrTeamFilter": "ALL_AVAILABLE",
                        "pageNumber": str(page),
                        "maxResultsPerPage": "500",
                        "view": "STATS",
                    },
                }]
            }
            resp = session.post(
                FANTRAX_API,
                params={"leagueId": league_id},
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            top = data["responses"][0]["data"]

            for row in top.get("statsTable", []):
                name = row.get("scorer", {}).get("name", "")
                if name:
                    available.add(name)

            pagination = top.get("paginatedResultSet", {})
            total_pages = int(pagination.get("totalNumPages", 1))
            if page >= total_pages:
                break
            page += 1

    except Exception as e:
        print(f"fetch_available_players error: {e}")

    return available


# ── Consensus prospect rankings ───────────────────────────────────────────────

# 2026 consensus top 100 — sourced from MLB Pipeline top 100 (primary),
# cross-referenced with justbaseball.com and theScore composite (March 2026).
# Graduated MLB players (Basallo, McLean, Chandler, etc.) are filtered at runtime
# by get_consensus_rankings(). Blake Mitchell is #75 on Pipeline only and does
# not appear on other lists — excluded from this list intentionally.
CONSENSUS_TOP_100 = [
    ("Konnor Griffin",        "SS",  "PIT", 19,  1),
    ("Kevin McGonigle",       "SS",  "DET", 21,  2),
    ("Jesus Made",            "SS",  "MIL", 18,  3),
    ("Leo De Vries",          "SS",  "OAK", 19,  4),
    ("Colt Emerson",          "SS",  "SEA", 20,  5),
    ("Nolan McLean",          "RHP", "NYM", 24,  6),  # graduated — filtered at runtime
    ("JJ Wetherholt",         "SS",  "STL", 23,  7),
    ("Aidan Miller",          "SS",  "PHI", 21,  8),
    ("Samuel Basallo",        "C",   "BAL", 21,  9),  # graduated — filtered at runtime
    ("Max Clark",             "OF",  "DET", 21, 10),
    ("Bubba Chandler",        "RHP", "PIT", 23, 11),  # graduated — filtered at runtime
    ("Carson Benge",          "OF",  "NYM", 23, 12),
    ("Carter Jensen",         "C",   "KC",  22, 13),  # graduated — filtered at runtime
    ("Trey Yesavage",         "RHP", "TOR", 22, 14),  # graduated — filtered at runtime
    ("Sal Stewart",           "3B",  "CIN", 22, 15),  # graduated — filtered at runtime
    ("Walker Jenkins",        "OF",  "MIN", 21, 16),
    ("Bryce Eldridge",        "1B",  "SF",  21, 17),  # graduated — filtered at runtime
    ("Luis Pena",             "SS",  "MIL", 19, 18),
    ("Thomas White",          "LHP", "MIA", 21, 19),
    ("Chase DeLauter",        "OF",  "CLE", 24, 20),  # graduated — filtered at runtime
    ("Andrew Painter",        "RHP", "PHI", 22, 21),
    ("Eli Willits",           "SS",  "WSH", 18, 22),
    ("Connelly Early",        "LHP", "BOS", 23, 23),  # graduated — filtered at runtime
    ("Rainiel Rodriguez",     "C",   "STL", 19, 24),
    ("Robby Snelling",        "LHP", "MIA", 22, 25),
    ("Kade Anderson",         "LHP", "SEA", 21, 26),
    ("Zyhir Hope",            "OF",  "LAD", 21, 27),
    ("Payton Tolle",          "LHP", "BOS", 23, 28),  # graduated — filtered at runtime
    ("Ryan Sloan",            "RHP", "SEA", 20, 29),
    ("Jonah Tong",            "RHP", "NYM", 22, 30),  # graduated — filtered at runtime
    ("Edward Florentino",     "OF",  "PIT", 19, 31),
    ("Sebastian Walcott",     "SS",  "TEX", 19, 32),
    ("Dylan Beavers",         "OF",  "BAL", 24, 33),  # graduated — filtered at runtime
    ("Mike Sirota",           "OF",  "LAD", 22, 34),
    ("Bryce Rainer",          "SS",  "DET", 20, 35),
    ("Josue Briceno",         "C",   "DET", 21, 36),
    ("Joe Mack",              "C",   "MIA", 23, 37),
    ("Brody Hopkins",         "RHP", "TB",  24, 38),
    ("Franklin Arias",        "SS",  "BOS", 20, 39),
    ("Eduardo Quintero",      "OF",  "LAD", 20, 40),
    ("Josue De Paula",        "OF",  "LAD", 20, 41),
    ("Alfredo Duno",          "C",   "CIN", 20, 42),
    ("AJ Ewing",              "OF",  "NYM", 21, 43),
    ("Ryan Waldschmidt",      "OF",  "ARI", 23, 44),
    ("Jett Williams",         "SS",  "MIL", 22, 45),
    ("Travis Bazzana",        "2B",  "CLE", 23, 46),
    ("Caleb Bonemer",         "SS",  "CHW", 20, 47),
    ("Owen Caissie",          "OF",  "MIA", 23, 48),
    ("Seth Hernandez",        "RHP", "PIT", 19, 49),
    ("Emmanuel Rodriguez",    "OF",  "MIN", 23, 50),
    ("Aiva Arquette",         "SS",  "MIA", 22, 51),
    ("Gage Jump",             "LHP", "OAK", 22, 52),
    ("George Lombard Jr.",    "SS",  "NYY", 20, 53),
    ("Jarlin Susana",         "RHP", "WSH", 21, 54),
    ("Moises Ballesteros",    "C",   "CHC", 22, 55),  # graduated — filtered at runtime
    ("Eduardo Tait",          "C",   "MIN", 19, 56),
    ("Ralphy Velazquez",      "1B",  "CLE", 20, 57),
    ("Josuar Gonzalez",       "SS",  "SF",  18, 58),
    ("Jaxon Wiggins",         "RHP", "CHC", 24, 59),
    ("Ethan Holliday",        "SS",  "COL", 19, 60),
    ("JoJo Parker",           "SS",  "TOR", 19, 61),
    ("Braden Montgomery",     "OF",  "CHW", 22, 62),
    ("River Ryan",            "RHP", "LAD", 27, 63),  # graduated — filtered at runtime
    ("Carlos Lagrange",       "RHP", "NYY", 22, 64),
    ("Noah Schultz",          "LHP", "CHW", 22, 65),
    ("George Klassen",        "RHP", "LAA", 24, 66),
    ("Travis Sykora",         "RHP", "WSH", 21, 67),
    ("Carson Williams",       "SS",  "TB",  22, 68),  # graduated — filtered at runtime
    ("Luis Perales",          "RHP", "WSH", 22, 69),
    ("Liam Doyle",            "LHP", "STL", 21, 70),
    ("Brandon Sproat",        "RHP", "MIL", 25, 71),  # graduated — filtered at runtime
    ("Angel Genao",           "SS",  "CLE", 21, 72),
    ("Jonny Farmelo",         "OF",  "SEA", 21, 73),
    ("Harry Ford",            "C",   "WSH", 23, 74),  # graduated — filtered at runtime
    ("Theo Gillen",           "OF",  "TB",  20, 75),
    ("Dax Kilby",             "SS",  "NYY", 19, 76),
    ("Lazaro Montes",         "OF",  "SEA", 21, 77),
    ("Caden Scarborough",     "RHP", "TEX", 20, 78),
    ("Justin Crawford",       "OF",  "PHI", 22, 79),
    ("Jhostynxon Garcia",     "OF",  "PIT", 23, 80),  # graduated — filtered at runtime
    ("Ryan Clifford",         "1B",  "NYM", 22, 81),
    ("Trey Gibson",           "RHP", "BAL", 23, 82),
    ("JR Ritchie",            "RHP", "ATL", 22, 83),
    ("Kaelen Culpepper",      "SS",  "MIN", 23, 84),
    ("Jeferson Quero",        "C",   "MIL", 23, 85),
    ("Juneiker Caceres",      "OF",  "CLE", 18, 86),
    ("Jack Wenninger",        "RHP", "NYM", 23, 87),
    ("Charlee Soto",          "RHP", "MIN", 20, 88),
    ("Rhett Lowder",          "RHP", "CIN", 24, 89),  # graduated — filtered at runtime
    ("Alex Freeland",         "SS",  "LAD", 24, 90),  # graduated — filtered at runtime
    ("Bo Davidson",           "OF",  "SF",  23, 91),
    ("Logan Henderson",       "RHP", "MIL", 24, 92),  # graduated — filtered at runtime
    ("Jacob Reimer",          "3B",  "NYM", 22, 93),
    ("Charlie Condon",        "1B",  "COL", 22, 94),
    ("Arjun Nimmala",         "SS",  "TOR", 20, 95),
    ("Kendry Chourio",        "RHP", "KC",  18, 96),
    ("Jurrangelo Cijntje",    "RHP", "SEA", 22, 97),
    ("Cam Caminiti",          "LHP", "ATL", 19, 98),
    ("Jimmy Crooks",          "C",   "STL", 24, 99),
    ("Ethan Salas",           "C",   "SD",  19, 100),
]


def get_consensus_rankings() -> pd.DataFrame:
    """
    Returns deduplicated consensus top 100, filtered to remove
    players who have graduated (have an MLB debut date).
    """
    df = pd.DataFrame(CONSENSUS_TOP_100, columns=["name", "position", "org", "age", "consensus_rank"])
    df = df.drop_duplicates("name").reset_index(drop=True)

    # Filter out graduated players via MLB Stats API
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/sports/1/players",
            params={"season": 2026},
            timeout=15,
        )
        resp.raise_for_status()
        graduated = set()
        for p in resp.json().get("people", []):
            if p.get("mlbDebutDate"):
                graduated.add(p.get("fullName", "").lower())

        df = df[df["name"].apply(lambda n: n.lower() not in graduated)].reset_index(drop=True)
    except Exception as e:
        print(f"Graduation filter error: {e}")

    return df


# ── Level-for-age scoring ─────────────────────────────────────────────────────

# Numeric level values: higher = more advanced
_LEVEL_ORDER = {"Rk": 1, "CPX": 1, "A": 2, "A+": 3, "AA": 4, "AAA": 5, "MLB": 6}

# What level is "on track" for each age
_AGE_EXPECTED_LEVEL = {
    18: 2,   # A ball is on track
    19: 2,   # A/A+ on track
    20: 3,   # A+ on track
    21: 3,   # A+/AA on track
    22: 4,   # AA on track
    23: 4,   # AA/AAA on track
    24: 5,   # AAA on track
    25: 5,   # AAA on track
    26: 6,   # should be MLB
}

def _level_for_age_score(age, level_str) -> float:
    """
    0-100 score based on how advanced the player is for their age.
    On track = 50. One level ahead = 75. Two levels ahead = 100.
    One level behind = 25. Two behind = 5.
    """
    if not level_str or pd.isna(level_str):
        return 50.0
    level_val = _LEVEL_ORDER.get(str(level_str).strip(), 3)
    age_int = int(age) if pd.notna(age) else 22
    expected = _AGE_EXPECTED_LEVEL.get(min(max(age_int, 18), 26), 4)
    diff = level_val - expected  # positive = ahead of schedule
    score = 50.0 + diff * 25.0
    return float(max(5.0, min(100.0, score)))


# ── Main function ─────────────────────────────────────────────────────────────

def get_available_prospects(league_id: str, session: requests.Session, rostered_names: set[str] = None) -> pd.DataFrame:
    """
    Returns a DataFrame of top prospects available on the waiver wire.

    Dynasty value formula (4 components):
      1. Pedigree     (40%) — consensus rank → 0-100. The hype/eye-test score.
      2. Production   (25%) — MiLB stats (OPS/HR/SB or ERA/K9/WHIP). 0-100.
      3. Level-for-age(20%) — how advanced vs expected for their age. 0-100.
      4. Age multiplier     — final multiplier so younger players rank higher.

    When no production data exists, weights shift to 70% pedigree / 30% level-for-age.
    """
    from dynasty import _base_age_mult as _age_multiplier
    from milb_stats import get_milb_production_scores, fetch_milb_id_map, lookup_id, get_milb_slug

    rankings = get_consensus_rankings()

    # ── 0. Resolve mlb_id for every prospect ─────────────────────────────────
    id_map = fetch_milb_id_map()
    rankings["mlb_id"] = rankings["name"].apply(lambda n: lookup_id(n, id_map))

    # ── 1. Pedigree score ─────────────────────────────────────────────────────
    rankings["pedigree_score"] = (101 - rankings["consensus_rank"]).clip(1, 100).astype(float)

    # ── 2. MiLB production — fetch by ID so no one gets missed ───────────────
    known_ids = [int(i) for i in rankings["mlb_id"].dropna().unique()]
    production = get_milb_production_scores(season=2025, player_ids=known_ids)

    if not production.empty:
        # Map stats back by mlb_id (avoids name-matching entirely)
        stat_cols = ["mlb_id", "production_score", "level",
                     "ab", "ops", "hr", "sb", "ip", "era", "k9", "whip"]
        prod_sub = production[[c for c in stat_cols if c in production.columns]].rename(
            columns={"level": "milb_level"}
        )
        rankings = rankings.merge(prod_sub, on="mlb_id", how="left")
    else:
        for col in ["production_score", "milb_level", "ab", "ops", "hr", "sb",
                    "ip", "era", "k9", "whip"]:
            rankings[col] = None

    # ── 3. Level-for-age score ────────────────────────────────────────────────
    rankings["level_age_score"] = rankings.apply(
        lambda r: _level_for_age_score(r["age"], r.get("milb_level")), axis=1
    )

    # ── 4. Blend + age multiplier ─────────────────────────────────────────────
    rankings["age_multiplier"] = rankings["age"].apply(
        lambda a: _age_multiplier(int(a) if pd.notna(a) else 22)
    )

    def _dynasty_value(row):
        pedigree  = float(row["pedigree_score"])
        level_age = float(row["level_age_score"])
        prod      = row.get("production_score")
        has_prod  = pd.notna(prod) and float(prod) > 0

        if has_prod:
            blended = 0.40 * pedigree + 0.25 * float(prod) + 0.20 * level_age + 0.15 * pedigree
        else:
            blended = 0.70 * pedigree + 0.30 * level_age

        return round(blended * float(row["age_multiplier"]), 1)

    rankings["dynasty_value"] = rankings.apply(_dynasty_value, axis=1)

    # ── Availability check ────────────────────────────────────────────────────
    available = fetch_available_players(league_id, session)
    if available:
        rankings["available"] = rankings["name"].apply(
            lambda n: any(n.lower() in a.lower() or a.lower() in n.lower() for a in available)
        )
    elif rostered_names:
        def is_available(name):
            name_lower = name.lower()
            for r in rostered_names:
                if name_lower in r.lower() or r.lower() in name_lower:
                    return False
            return True
        rankings["available"] = rankings["name"].apply(is_available)
    else:
        rankings["available"] = None

    return rankings.sort_values("consensus_rank", ascending=True).reset_index(drop=True)
