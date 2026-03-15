"""
Fetches real MLB stats and recent Fantrax game log for a player.
Used in the player profile dialog.
"""
import requests
import pandas as pd

MLB_API = "https://statsapi.mlb.com/api/v1"
FANTRAX_API = "https://www.fantrax.com/fxpa/req"


# ── MLB real stats ────────────────────────────────────────────────────────────

def fetch_mlb_stats(mlb_id: int, season: int = 2025) -> dict:
    """
    Returns a dict with hitting or pitching stats for the given MLB player ID.
    Tries hitting first, falls back to pitching.
    """
    if not mlb_id:
        return {}
    try:
        resp = requests.get(
            f"{MLB_API}/people/{mlb_id}/stats",
            params={
                "stats": "season",
                "season": season,
                "group": "hitting,pitching",
                "sportId": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        stats_list = resp.json().get("stats", [])
        result = {}
        for group in stats_list:
            splits = group.get("splits", [])
            if not splits:
                continue
            s = splits[0].get("stat", {})
            group_name = group.get("group", {}).get("displayName", "")
            if group_name == "hitting":
                result["type"] = "hitter"
                result.update({
                    "avg":    s.get("avg", "—"),
                    "obp":    s.get("obp", "—"),
                    "slg":    s.get("slg", "—"),
                    "ops":    s.get("ops", "—"),
                    "hr":     s.get("homeRuns", "—"),
                    "rbi":    s.get("rbi", "—"),
                    "sb":     s.get("stolenBases", "—"),
                    "hits":   s.get("hits", "—"),
                    "ab":     s.get("atBats", "—"),
                    "games":  s.get("gamesPlayed", "—"),
                    "k_pct":  _pct(s.get("strikeOuts"), s.get("plateAppearances")),
                    "bb_pct": _pct(s.get("baseOnBalls"), s.get("plateAppearances")),
                })
            elif group_name == "pitching":
                if result.get("type") == "hitter":
                    continue  # prefer hitting if both exist (two-way)
                result["type"] = "pitcher"
                result.update({
                    "era":    s.get("era", "—"),
                    "whip":   s.get("whip", "—"),
                    "wins":   s.get("wins", "—"),
                    "losses": s.get("losses", "—"),
                    "saves":  s.get("saves", "—"),
                    "ip":     s.get("inningsPitched", "—"),
                    "so":     s.get("strikeOuts", "—"),
                    "bb":     s.get("baseOnBalls", "—"),
                    "k9":     s.get("strikeoutsPer9Inn", "—"),
                    "bb9":    s.get("walksPer9Inn", "—"),
                    "games":  s.get("gamesPlayed", "—"),
                    "fip":    s.get("fielding", {}).get("fip", "—") if isinstance(s.get("fielding"), dict) else "—",
                })
        return result
    except Exception as e:
        print(f"fetch_mlb_stats error: {e}")
        return {}


def _pct(num, denom):
    try:
        return f"{float(num) / float(denom) * 100:.1f}%"
    except Exception:
        return "—"


# ── Fantrax recent game log ───────────────────────────────────────────────────

def fetch_recent_game_log(
    player_name: str,
    league_id: str,
    session: requests.Session,
    n: int = 10,
) -> pd.DataFrame:
    """
    Fetches the most recent N fantasy scoring periods for a player.
    Returns DataFrame with columns: Date, FPts, FP/G, and key stat columns.
    """
    try:
        payload = {
            "msgs": [{
                "method": "getPlayerStats",
                "data": {
                    "leagueId": league_id,
                    "reload": "1",
                    "statusOrTeamFilter": "ALL",
                    "pageNumber": "1",
                    "maxResultsPerPage": "500",
                    "view": "GAME_LOG",
                    "sortType": "SCORE",
                    "seasonOrProjection": "SEASON_145_YEAR_TO_DATE",
                },
            }]
        }
        resp = session.post(
            FANTRAX_API,
            params={"leagueId": league_id},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        top = data["responses"][0]["data"]

        # Find the player row
        target = None
        for row in top.get("statsTable", []):
            if row.get("scorer", {}).get("name", "").lower() == player_name.lower():
                target = row
                break

        if not target:
            return pd.DataFrame()

        # Game log is in the "gameLogs" or similar key — try common structures
        game_logs = target.get("gameLogs") or target.get("gameLog") or []
        if not game_logs:
            return pd.DataFrame()

        rows = []
        for g in game_logs[-n:]:
            rows.append({
                "Date":  g.get("date", g.get("period", "?")),
                "Opp":   g.get("opponent", g.get("opp", "?")),
                "FPts":  _safe_float(g.get("score", g.get("fpts", g.get("fantasyPoints")))),
            })

        df = pd.DataFrame(rows)
        return df.iloc[::-1].reset_index(drop=True)  # most recent first

    except Exception as e:
        print(f"fetch_recent_game_log error: {e}")
        return pd.DataFrame()


def _safe_float(val):
    try:
        return round(float(val), 1)
    except Exception:
        return None
