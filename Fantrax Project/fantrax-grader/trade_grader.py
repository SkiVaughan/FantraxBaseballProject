"""
Past Trade Grader — fetches all historical trades from Fantrax and grades them.
"""
import re
import requests
import pandas as pd
from datetime import datetime

FANTRAX_API = "https://www.fantrax.com/fxpa/req"
LEAGUE_ID   = "hp3gi9z9mg6wf2p7"


def fetch_trade_history(session: requests.Session) -> list[dict]:
    """Fetches all trade transactions from Fantrax."""
    trades = []
    for method in ["getTransactions", "getLeagueTransactions", "getRecentTransactions"]:
        try:
            payload = {
                "msgs": [{
                    "method": method,
                    "data": {
                        "leagueId": LEAGUE_ID,
                        "transactionType": "TRADE",
                        "maxResults": "500",
                    },
                }]
            }
            resp = session.post(
                FANTRAX_API,
                params={"leagueId": LEAGUE_ID},
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            responses = data.get("responses", [{}])
            if not responses:
                continue
            top = responses[0].get("data", {})
            for key in ["transactions", "tradeList", "trades", "transactionList"]:
                items = top.get(key, [])
                if items:
                    trades = items
                    print(f"fetch_trade_history: {len(trades)} trades via {method}/{key}")
                    return trades
            if top:
                print(f"fetch_trade_history: {method} returned keys: {list(top.keys())}")
        except Exception as e:
            print(f"fetch_trade_history {method} error: {e}")
            continue
    return trades



def fetch_draft_results(session: requests.Session) -> dict:
    """Fetches draft results to resolve pick -> player mappings."""
    pick_map = {}
    try:
        payload = {
            "msgs": [{
                "method": "getDraftResults",
                "data": {"leagueId": LEAGUE_ID},
            }]
        }
        resp = session.post(
            FANTRAX_API,
            params={"leagueId": LEAGUE_ID},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        top = data.get("responses", [{}])[0].get("data", {})
        for key in ["draftResults", "picks", "draftPicks", "results"]:
            picks = top.get(key, [])
            if picks:
                for pick in picks:
                    round_num = pick.get("round", pick.get("roundNum", ""))
                    pick_num  = pick.get("pick",  pick.get("pickNum", ""))
                    player    = (
                        pick.get("playerName") or
                        pick.get("player", {}).get("name", "") or
                        pick.get("name", "")
                    )
                    if round_num and pick_num and player:
                        key_str = f"{round_num}.{str(pick_num).zfill(2)}"
                        pick_map[key_str] = player
                break
    except Exception as e:
        print(f"fetch_draft_results error: {e}")
    return pick_map


_PICK_RE  = re.compile(r"(\d{4})\s+(?:round\s+)?(\d+)(?:st|nd|rd|th)?\s+(?:round\s+)?pick", re.IGNORECASE)
_PICK_RE2 = re.compile(r"pick\s+(\d+)\.(\d+)", re.IGNORECASE)


def _is_pick(name: str) -> bool:
    return bool(_PICK_RE.search(name) or _PICK_RE2.search(name) or
                re.search(r"\bpick\b", name, re.IGNORECASE))


def _parse_pick_key(name: str):
    m = _PICK_RE2.search(name)
    if m:
        return f"{m.group(1)}.{m.group(2).zfill(2)}"
    m = _PICK_RE.search(name)
    if m:
        return f"{m.group(1)}.{m.group(2).zfill(2)}"
    return None



def parse_trades(raw_trades: list, pick_map: dict) -> list:
    """Normalises raw Fantrax trade data into a consistent structure."""
    parsed = []
    for raw in raw_trades:
        try:
            trade_id = str(raw.get("id") or raw.get("tradeId") or raw.get("transactionId") or "")
            date_str = (
                raw.get("date") or raw.get("processedDate") or
                raw.get("timestamp") or raw.get("createdDate") or ""
            )
            date_obj = None
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    date_obj = datetime.strptime(str(date_str)[:19], fmt)
                    break
                except ValueError:
                    continue
            date_display = date_obj.strftime("%Y-%m-%d") if date_obj else str(date_str)[:10]
            year = date_obj.year if date_obj else None

            team_a, team_b = "", ""
            a_gets_raw, b_gets_raw = [], []

            sides = raw.get("sides") or raw.get("tradeSides") or []
            if sides and len(sides) >= 2:
                team_a = sides[0].get("teamName") or sides[0].get("team", {}).get("name", "")
                team_b = sides[1].get("teamName") or sides[1].get("team", {}).get("name", "")
                for item in sides[0].get("players", sides[0].get("items", [])):
                    a_gets_raw.append(item.get("playerName") or item.get("name") or item.get("player", {}).get("name", ""))
                for item in sides[1].get("players", sides[1].get("items", [])):
                    b_gets_raw.append(item.get("playerName") or item.get("name") or item.get("player", {}).get("name", ""))
            elif raw.get("teamA") or raw.get("team1"):
                team_a = raw.get("teamA") or raw.get("team1", {}).get("name", "")
                team_b = raw.get("teamB") or raw.get("team2", {}).get("name", "")
                a_gets_raw = [p.get("name", "") for p in (raw.get("teamAPlayers") or raw.get("team1Players") or [])]
                b_gets_raw = [p.get("name", "") for p in (raw.get("teamBPlayers") or raw.get("team2Players") or [])]
            elif raw.get("items") or raw.get("players"):
                items = raw.get("items") or raw.get("players") or []
                for item in items:
                    from_team = item.get("fromTeam") or item.get("fromTeamName") or ""
                    to_team   = item.get("toTeam")   or item.get("toTeamName")   or ""
                    pname     = item.get("playerName") or item.get("name") or ""
                    if from_team and to_team:
                        if not team_a:
                            team_a, team_b = from_team, to_team
                        if from_team == team_a:
                            b_gets_raw.append(pname)
                        else:
                            a_gets_raw.append(pname)

            if not team_a or not team_b:
                continue

            def _resolve(name):
                is_p = _is_pick(name)
                resolved = None
                if is_p:
                    k = _parse_pick_key(name)
                    if k:
                        resolved = pick_map.get(k)
                return {"name": name, "is_pick": is_p, "resolved_player": resolved}

            a_gets = [_resolve(n) for n in a_gets_raw if n]
            b_gets = [_resolve(n) for n in b_gets_raw if n]
            if not a_gets and not b_gets:
                continue

            parsed.append({
                "trade_id": trade_id,
                "date":     date_display,
                "year":     year,
                "team_a":   team_a,
                "team_b":   team_b,
                "a_gets":   a_gets,
                "b_gets":   b_gets,
            })
        except Exception as e:
            print(f"parse_trades error: {e}")
            continue

    parsed.sort(key=lambda x: x["date"], reverse=True)
    return parsed



def build_trade_tree(trades: list) -> dict:
    """Returns {player_name_lower: [trade, ...]} for players in 2+ trades."""
    player_trades = {}
    for trade in trades:
        for item in trade["a_gets"] + trade["b_gets"]:
            key = (item.get("resolved_player") or item["name"]).strip().lower()
            if key not in player_trades:
                player_trades[key] = []
            player_trades[key].append(trade)
    return {k: v for k, v in player_trades.items() if len(v) >= 2}


def _player_value(name, is_pick, resolved_player, history_df, graded_df, prospects_df) -> dict:
    """Compute composite trade value for one player/pick."""
    score_name = resolved_player if (is_pick and resolved_player) else name
    fpts_2025 = fpts_2024 = fpts_proj = 0.0
    grade = position = "?"
    prospect_value = 0.0
    is_prospect = False

    if history_df is not None and not history_df.empty and score_name:
        h = history_df[history_df["name"].str.lower() == score_name.lower()]
        if not h.empty:
            r = h.iloc[0]
            fpts_2025 = float(r.get("fpts_2025", 0) or 0)
            fpts_2024 = float(r.get("fpts_2024", 0) or 0)
            fpts_proj = float(r.get("fpts_proj",  0) or 0)

    if graded_df is not None and not graded_df.empty and score_name:
        g = graded_df[graded_df["name"].str.lower() == score_name.lower()]
        if not g.empty:
            r = g.iloc[0]
            grade    = r.get("grade", "?")
            position = r.get("position", "?")

    if prospects_df is not None and not prospects_df.empty and score_name:
        p = prospects_df[prospects_df["name"].str.lower() == score_name.lower()]
        if not p.empty:
            r = p.iloc[0]
            prospect_value = float(r.get("dynasty_value", 0) or 0)
            is_prospect = True
            if not position or position == "?":
                position = r.get("position", "?")

    weighted_fpts = fpts_proj * 0.40 + fpts_2025 * 0.35 + fpts_2024 * 0.25
    if weighted_fpts > 10:
        total_value = weighted_fpts + prospect_value * 0.5
    elif prospect_value > 0:
        total_value = prospect_value * 4.0
    elif is_pick and not resolved_player:
        total_value = 150.0
    else:
        total_value = 0.0

    return {
        "name":            name,
        "score_name":      score_name,
        "is_pick":         is_pick,
        "resolved_player": resolved_player,
        "is_prospect":     is_prospect,
        "position":        position,
        "grade":           grade,
        "fpts_2025":       fpts_2025,
        "fpts_2024":       fpts_2024,
        "fpts_proj":       fpts_proj,
        "prospect_value":  prospect_value,
        "total_value":     round(total_value, 1),
    }


def grade_trade(trade, history_df, graded_df, prospects_df) -> dict:
    """Grade one parsed trade, returning enriched dict with totals and verdict."""
    a_players = [
        _player_value(i["name"], i["is_pick"], i["resolved_player"], history_df, graded_df, prospects_df)
        for i in trade["a_gets"]
    ]
    b_players = [
        _player_value(i["name"], i["is_pick"], i["resolved_player"], history_df, graded_df, prospects_df)
        for i in trade["b_gets"]
    ]
    a_total = sum(p["total_value"] for p in a_players)
    b_total = sum(p["total_value"] for p in b_players)
    diff    = round(a_total - b_total, 1)

    if abs(diff) < 30:
        verdict = "🤝 Even Trade"
    elif diff > 0:
        verdict = f"✅ {trade['team_a']} won"
    else:
        verdict = f"✅ {trade['team_b']} won"

    return {
        **trade,
        "a_players": a_players,
        "b_players": b_players,
        "a_total":   round(a_total, 1),
        "b_total":   round(b_total, 1),
        "diff":      diff,
        "verdict":   verdict,
    }


def load_and_grade_all_trades(session, history_df, graded_df, prospects_df):
    """
    Fetches, parses, and grades all trades in league history.
    Returns (graded_trades, trade_tree). Always returns a 2-tuple.
    """
    graded_trades = []
    trade_tree    = {}
    try:
        raw_trades = fetch_trade_history(session)
        if not raw_trades:
            print("load_and_grade_all_trades: no raw trades returned")
            return graded_trades, trade_tree

        pick_map = fetch_draft_results(session)
        parsed   = parse_trades(raw_trades, pick_map)
        if not parsed:
            print("load_and_grade_all_trades: no trades parsed")
            return graded_trades, trade_tree

        for trade in parsed:
            try:
                graded_trades.append(grade_trade(trade, history_df, graded_df, prospects_df))
            except Exception as e:
                print(f"grade_trade error: {e}")

        trade_tree = build_trade_tree(parsed)
    except Exception as e:
        print(f"load_and_grade_all_trades error: {e}")
        import traceback; traceback.print_exc()

    return graded_trades, trade_tree
