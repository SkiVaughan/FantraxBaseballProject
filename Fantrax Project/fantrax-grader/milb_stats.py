"""
Fetches real MiLB stats from the MLB Stats API.

Strategy:
  1. fetch_milb_id_map()  — bulk-fetch all MiLB player IDs across all levels
  2. get_milb_production_scores() — fetch stats for a specific list of player IDs
     so we never miss a prospect due to leaderboard cutoffs or name mismatches.
"""
import re
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

MLB_API      = "https://statsapi.mlb.com/api/v1"
MILB_SPORT_IDS = "11,12,13,14,16"   # AAA, AA, High-A, A, Rookie

# Module-level caches
_id_map_cache:   dict[str, int] = {}   # lower_name → mlb_id
_slug_map_cache: dict[int, str] = {}   # mlb_id → nameSlug  (for URL building)


# ── Name normalisation ────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse spaces."""
    name = name.lower()
    # strip accents
    replacements = {
        "á":"a","à":"a","â":"a","ä":"a","ã":"a",
        "é":"e","è":"e","ê":"e","ë":"e",
        "í":"i","ì":"i","î":"i","ï":"i",
        "ó":"o","ò":"o","ô":"o","ö":"o","õ":"o",
        "ú":"u","ù":"u","û":"u","ü":"u",
        "ñ":"n","ç":"c",
    }
    for src, dst in replacements.items():
        name = name.replace(src, dst)
    # remove dots and apostrophes (J.J. → jj, O'Brien → obrien)
    name = re.sub(r"[.'`]", "", name)
    # collapse whitespace
    return " ".join(name.split())


# ── ID / slug map ─────────────────────────────────────────────────────────────

def fetch_milb_id_map(season: int = 2026) -> dict[str, int]:
    """
    Returns {normalised_name: mlb_id} for every active MiLB player.
    Also populates _slug_map_cache {mlb_id: nameSlug} for URL building.
    """
    global _id_map_cache, _slug_map_cache
    if _id_map_cache:
        return _id_map_cache

    result: dict[str, int] = {}
    slugs:  dict[int, str] = {}

    for sport_id in [11, 12, 13, 14, 16]:
        try:
            resp = requests.get(
                f"{MLB_API}/sports/{sport_id}/players",
                params={"season": season},
                timeout=20,
            )
            resp.raise_for_status()
            for p in resp.json().get("people", []):
                name = p.get("fullName", "")
                pid  = p.get("id")
                slug = p.get("nameSlug", "")
                if name and pid:
                    result[_norm(name)] = pid
                    if slug:
                        slugs[pid] = slug
        except Exception as e:
            print(f"fetch_milb_id_map sport {sport_id} error: {e}")
            continue

    _id_map_cache  = result
    _slug_map_cache = slugs
    return result


def get_milb_slug(mlb_id: int, name: str) -> str:
    """Returns the nameSlug for URL building, falling back to a generated slug."""
    slug = _slug_map_cache.get(mlb_id)
    if slug:
        return slug
    # generate: "First Last" → "first-last-{id}"
    generated = re.sub(r"[^a-z0-9]+", "-", _norm(name)).strip("-")
    return f"{generated}-{mlb_id}"


def lookup_id(name: str, id_map: dict[str, int] | None = None) -> int | None:
    """Find mlb_id for a prospect name with fuzzy fallback."""
    if id_map is None:
        id_map = fetch_milb_id_map()
    key = _norm(name)
    if key in id_map:
        return id_map[key]
    # fuzzy: last name + first initial
    parts = key.split()
    if len(parts) >= 2:
        last, fi = parts[-1], parts[0][0]
        for k, v in id_map.items():
            kp = k.split()
            if kp and kp[-1] == last and kp[0][0] == fi:
                return v
    return None


# ── Per-player stat fetch ─────────────────────────────────────────────────────

def _fetch_player_stats(mlb_id: int, season: int) -> dict:
    """Fetch season hitting + pitching stats for one player by ID."""
    try:
        resp = requests.get(
            f"{MLB_API}/people/{mlb_id}/stats",
            params={
                "stats":   "season",
                "season":  season,
                "group":   "hitting,pitching",
                "sportId": MILB_SPORT_IDS,
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = {"mlb_id": mlb_id}
        for group in resp.json().get("stats", []):
            splits = group.get("splits", [])
            if not splits:
                continue
            s    = splits[0].get("stat", {})
            gname = group.get("group", {}).get("displayName", "")
            level = splits[0].get("sport", {}).get("abbreviation", "")
            if gname == "hitting":
                result.update({
                    "level": level,
                    "ab":    int(s.get("atBats", 0) or 0),
                    "ops":   float(s.get("ops", 0) or 0),
                    "avg":   float(s.get("avg", 0) or 0),
                    "obp":   float(s.get("obp", 0) or 0),
                    "slg":   float(s.get("slg", 0) or 0),
                    "hr":    int(s.get("homeRuns", 0) or 0),
                    "sb":    int(s.get("stolenBases", 0) or 0),
                    "type":  "hitter",
                })
            elif gname == "pitching" and result.get("type") != "hitter":
                ip_str = str(s.get("inningsPitched", "0"))
                try:
                    ip = float(ip_str)
                except ValueError:
                    ip = 0.0
                result.update({
                    "level": level,
                    "ip":    ip,
                    "era":   float(s.get("era", 99) or 99),
                    "whip":  float(s.get("whip", 99) or 99),
                    "k9":    float(s.get("strikeoutsPer9Inn", 0) or 0),
                    "type":  "pitcher",
                })
        return result
    except Exception:
        return {"mlb_id": mlb_id}


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_hitter(row: dict) -> float | None:
    ab = row.get("ab", 0)
    if not ab or ab < 50:   # lower threshold — prospects may have fewer ABs
        return None
    ops_score = min(row.get("ops", 0) / 1.100, 1.0) * 60
    hr_score  = min(row.get("hr",  0) / 30,    1.0) * 20
    sb_score  = min(row.get("sb",  0) / 40,    1.0) * 20
    return round(ops_score + hr_score + sb_score, 1)


def score_pitcher(row: dict) -> float | None:
    ip = row.get("ip", 0)
    if not ip or ip < 30:   # lower threshold
        return None
    era_score  = max(0, (5.00 - row.get("era",  99)) / 5.00) * 40
    k9_score   = min(row.get("k9", 0) / 14, 1.0) * 40
    whip_score = max(0, (1.80 - row.get("whip", 99)) / 1.80) * 20
    return round(era_score + k9_score + whip_score, 1)


# ── Main entry point ──────────────────────────────────────────────────────────

def get_milb_production_scores(
    season: int = 2025,
    player_ids: list[int] | None = None,
) -> pd.DataFrame:
    """
    Returns a DataFrame with stats + production_score.

    If player_ids is provided, fetches stats for exactly those players
    (used by prospects.py to avoid leaderboard cutoffs).
    Otherwise falls back to bulk leaderboard fetch.
    """
    if player_ids:
        return _fetch_by_ids(player_ids, season)
    return _fetch_bulk(season)


def _fetch_by_ids(player_ids: list[int], season: int) -> pd.DataFrame:
    """Fetch stats for a specific list of player IDs in parallel."""
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_player_stats, pid, season): pid for pid in player_ids}
        for f in as_completed(futures):
            results.append(f.result())

    rows = []
    for r in results:
        if not r.get("type"):
            continue
        score = score_hitter(r) if r["type"] == "hitter" else score_pitcher(r)
        rows.append({**r, "production_score": score})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.reset_index(drop=True)


def _fetch_bulk(season: int) -> pd.DataFrame:
    """Fallback: bulk leaderboard fetch (may miss low-AB prospects)."""
    rows = []
    for group, sort_stat, extra_cols in [
        ("hitting",  "onBasePlusSlugging", ["ab","ops","hr","sb"]),
        ("pitching", "strikeoutsPer9Inn",  ["ip","era","k9","whip"]),
    ]:
        try:
            resp = requests.get(
                f"{MLB_API}/stats",
                params={
                    "stats":    "season",
                    "group":    group,
                    "sportIds": MILB_SPORT_IDS,
                    "season":   season,
                    "limit":    2000,
                    "offset":   0,
                    "sortStat": sort_stat,
                    "order":    "desc",
                },
                timeout=20,
            )
            resp.raise_for_status()
            for split in resp.json().get("stats", [{}])[0].get("splits", []):
                stat   = split.get("stat", {})
                player = split.get("player", {})
                level  = split.get("sport", {}).get("abbreviation", "")
                row = {
                    "name":   player.get("fullName", ""),
                    "mlb_id": player.get("id"),
                    "level":  level,
                    "type":   group[:-3] if group == "hitting" else "pitcher",
                }
                if group == "hitting":
                    row.update({
                        "ab":  int(stat.get("atBats", 0) or 0),
                        "ops": float(stat.get("ops", 0) or 0),
                        "hr":  int(stat.get("homeRuns", 0) or 0),
                        "sb":  int(stat.get("stolenBases", 0) or 0),
                    })
                    row["production_score"] = score_hitter(row)
                else:
                    ip_str = str(stat.get("inningsPitched", "0"))
                    try:
                        ip = float(ip_str)
                    except ValueError:
                        ip = 0.0
                    row.update({
                        "ip":   ip,
                        "era":  float(stat.get("era", 99) or 99),
                        "whip": float(stat.get("whip", 99) or 99),
                        "k9":   float(stat.get("strikeoutsPer9Inn", 0) or 0),
                    })
                    row["production_score"] = score_pitcher(row)
                rows.append(row)
        except Exception as e:
            print(f"_fetch_bulk {group} error: {e}")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["production_score"])
    df = df.sort_values("production_score", ascending=False)
    df = df.drop_duplicates("name", keep="first")
    return df.reset_index(drop=True)
