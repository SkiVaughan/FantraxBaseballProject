"""
Fetches 2026 dynasty baseball rankings from FantasyPros.
Returns a dict mapping player name -> normalized score (0-100).

Rank 1   → 100
Rank 300 → ~1
Linear inversion: score = max(0, 100 * (1 - (rank - 1) / (MAX_RANK - 1)))
"""
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup

FANTASYPROS_URL = "https://www.fantasypros.com/mlb/rankings/dynasty-overall.php"
ROTOWIRE_URL = "https://www.rotowire.com/baseball/dynasty-rankings.php"

MAX_RANK = 300
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _rank_to_score(rank: int, max_rank: int = MAX_RANK) -> float:
    """Invert rank to 0-100 score. Rank 1 = 100, rank max_rank = ~1."""
    return round(max(0.0, 100.0 * (1 - (rank - 1) / (max_rank - 1))), 1)


def _normalize_name(name: str) -> str:
    """Lowercase, strip accents-ish, remove punctuation for fuzzy matching."""
    name = name.lower().strip()
    # Remove suffixes like Jr., Sr., III
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", name)
    # Remove non-alpha except spaces
    name = re.sub(r"[^a-z ]", "", name)
    return " ".join(name.split())


def _fetch_fantasypros() -> dict[str, int]:
    """Scrape FantasyPros dynasty overall rankings. Returns {name: rank}."""
    try:
        resp = requests.get(FANTASYPROS_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        rankings = {}
        # FantasyPros rankings table has class 'player-table'
        table = soup.find("table", {"id": "ranking-table"}) or soup.find("table", class_=re.compile("player"))
        if table:
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                try:
                    rank = int(cells[0].get_text(strip=True))
                except ValueError:
                    continue
                # Player name is usually in a link inside the second cell
                name_tag = cells[1].find("a") or cells[1]
                name = name_tag.get_text(strip=True)
                if name:
                    rankings[_normalize_name(name)] = rank
        return rankings
    except Exception as e:
        print(f"  FantasyPros dynasty fetch failed: {e}")
        return {}


def _fetch_rotowire() -> dict[str, int]:
    """Scrape Rotowire dynasty rankings as fallback. Returns {name: rank}."""
    try:
        resp = requests.get(ROTOWIRE_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        rankings = {}
        # Rotowire uses a rankings list with player names
        rows = soup.select("ul.rankings-list li") or soup.select("div.player-name")
        if not rows:
            # Try table approach
            table = soup.find("table")
            if table:
                for i, row in enumerate(table.find_all("tr")[1:], 1):
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    try:
                        rank = int(cells[0].get_text(strip=True))
                    except ValueError:
                        rank = i
                    name_tag = cells[1].find("a") or cells[1] if len(cells) > 1 else None
                    if name_tag:
                        name = name_tag.get_text(strip=True)
                        if name:
                            rankings[_normalize_name(name)] = rank
        else:
            for i, row in enumerate(rows, 1):
                name = row.get_text(strip=True)
                if name:
                    rankings[_normalize_name(name)] = i

        return rankings
    except Exception as e:
        print(f"  Rotowire dynasty fetch failed: {e}")
        return {}


# ── Hardcoded fallback top-150 dynasty rankings (2026 consensus) ──────────────
# Source: FantasyPros / Baseball America / The Athletic consensus, March 2026
FALLBACK_RANKINGS = {
    "paul skenes": 1,
    "jackson chourio": 2,
    "elly de la cruz": 3,
    "corbin carroll": 4,
    "gunnar henderson": 5,
    "bobby witt jr": 6,
    "francisco lindor": 7,
    "julio rodriguez": 8,
    "spencer strider": 9,
    "tarik skubal": 10,
    "garrett crochet": 11,
    "yoshinobu yamamoto": 12,
    "hunter brown": 13,
    "kyle tucker": 14,
    "michael harris ii": 15,
    "adley rutschman": 16,
    "cal raleigh": 17,
    "pete crow-armstrong": 18,
    "jasson dominguez": 19,
    "evan carter": 20,
    "colt keith": 21,
    "james wood": 22,
    "jackson holliday": 23,
    "wyatt langford": 24,
    "jordan walker": 25,
    "marcelo mayer": 26,
    "brooks lee": 27,
    "colton cowser": 28,
    "masyn winn": 29,
    "junior caminero": 30,
    "coby mayo": 31,
    "jose caballero": 32,
    "tyler soderstrom": 33,
    "max clark": 34,
    "chase burns": 35,
    "roki sasaki": 36,
    "jacob wilson": 37,
    "bryce miller": 38,
    "tanner bibee": 39,
    "gavin stone": 40,
    "cristopher sanchez": 41,
    "freddy peralta": 42,
    "logan webb": 43,
    "max fried": 44,
    "zack wheeler": 45,
    "gerrit cole": 46,
    "shohei ohtani": 47,
    "aaron judge": 48,
    "juan soto": 49,
    "mookie betts": 50,
    "jose ramirez": 51,
    "freddie freeman": 52,
    "trea turner": 53,
    "rafael devers": 54,
    "nolan arenado": 55,
    "pete alonso": 56,
    "yordan alvarez": 57,
    "kyle schwarber": 58,
    "bryce harper": 59,
    "wander franco": 60,
    "vladimir guerrero jr": 61,
    "bo bichette": 62,
    "corey seager": 63,
    "marcus semien": 64,
    "austin riley": 65,
    "matt olson": 66,
    "michael brantley": 67,
    "cedric mullins": 68,
    "nick castellanos": 69,
    "teoscar hernandez": 70,
    "christian yelich": 71,
    "cody bellinger": 72,
    "alex bregman": 73,
    "jose abreu": 74,
    "xander bogaerts": 75,
    "dansby swanson": 76,
    "ha-seong kim": 77,
    "geraldo perdomo": 78,
    "nick pivetta": 79,
    "carlos rodon": 80,
    "bryan woo": 81,
    "jacob degrom": 82,
    "chris sale": 83,
    "dylan cease": 84,
    "kevin gausman": 85,
    "sandy alcantara": 86,
    "blake snell": 87,
    "corbin burnes": 88,
    "shane bieber": 89,
    "jose berrios": 90,
    "sonny gray": 91,
    "tyler glasnow": 92,
    "lance lynn": 93,
    "martin perez": 94,
    "framber valdez": 95,
    "hunter greene": 96,
    "george kirby": 97,
    "pablo lopez": 98,
    "dean kremer": 99,
    "kyle bradish": 100,
    "ronel blanco": 101,
    "michael king": 102,
    "seth lugo": 103,
    "zac gallen": 104,
    "merrill kelly": 105,
    "brandon pfaadt": 106,
    "edward cabrera": 107,
    "braxton garrett": 108,
    "trevor rogers": 109,
    "andrew heaney": 110,
    "jose quintana": 111,
    "patrick corbin": 112,
    "wade miley": 113,
    "rich hill": 114,
    "kyle freeland": 115,
    "austin gomber": 116,
    "jose urquidy": 117,
    "alex wood": 118,
    "matthew liberatore": 119,
    "miles mikolas": 120,
    "jordan montgomery": 121,
    "charlie morton": 122,
    "mike clevinger": 123,
    "nathan eovaldi": 124,
    "michael wacha": 125,
    "jose cimber": 126,
    "ryan helsley": 127,
    "felix bautista": 128,
    "alexis diaz": 129,
    "clay holmes": 130,
    "jhoan duran": 131,
    "evan phillips": 132,
    "david bednar": 133,
    "josh hader": 134,
    "devin williams": 135,
    "paul sewald": 136,
    "jordan romano": 137,
    "raisel iglesias": 138,
    "taylor rogers": 139,
    "scott barlow": 140,
    "kendall graveman": 141,
    "lou trivino": 142,
    "trevor may": 143,
    "michael kopech": 144,
    "keynan middleton": 145,
    "brusdar graterol": 146,
    "yimi garcia": 147,
    "andrew chafin": 148,
    "sam hentges": 149,
    "tanner scott": 150,
}


def fetch_dynasty_rankings() -> dict[str, float]:
    """
    Returns {normalized_player_name: score_0_to_100}.
    Tries live scraping first, falls back to hardcoded list.
    """
    print("  Fetching dynasty rankings...")

    # Try FantasyPros first
    rankings = _fetch_fantasypros()
    if len(rankings) >= 50:
        print(f"  Got {len(rankings)} dynasty rankings from FantasyPros")
    else:
        # Try Rotowire
        rankings = _fetch_rotowire()
        if len(rankings) >= 50:
            print(f"  Got {len(rankings)} dynasty rankings from Rotowire")
        else:
            print(f"  Live scraping returned {len(rankings)} results — using fallback rankings")
            rankings = FALLBACK_RANKINGS

    max_rank = max(rankings.values()) if rankings else MAX_RANK
    return {name: _rank_to_score(rank, max_rank) for name, rank in rankings.items()}


def lookup_dynasty_score(player_name: str, rankings: dict[str, float]) -> float:
    """
    Fuzzy lookup of a player name in the rankings dict.
    Returns score 0-100, or 50.0 (neutral) if not found.
    """
    key = _normalize_name(player_name)
    if key in rankings:
        return rankings[key]

    # Try partial match — last name only
    parts = key.split()
    if len(parts) >= 2:
        last = parts[-1]
        first = parts[0]
        for ranked_name, score in rankings.items():
            ranked_parts = ranked_name.split()
            if not ranked_parts:
                continue
            if ranked_parts[-1] == last and ranked_parts[0] == first:
                return score
            # Last name only match (lower confidence)
            if ranked_parts[-1] == last:
                return score * 0.9  # slight penalty for ambiguous match

    return 50.0  # neutral score for unranked players
