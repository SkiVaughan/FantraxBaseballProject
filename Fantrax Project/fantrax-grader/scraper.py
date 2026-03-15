"""
Fetches league data from Fantrax and returns structured DataFrames.
Import auth first to patch the request function with cookie support.
"""
import re
import auth  # noqa: F401 — patches api.request with cookie auth

import pandas as pd
from fantraxapi import League

LEAGUE_ID = "hp3gi9z9mg6wf2p7"


def get_league() -> League:
    return League(LEAGUE_ID)


def get_standings(league: League) -> pd.DataFrame:
    standings = league.standings()
    rows = []
    for record in standings.ranks.values():
        rows.append({
            "rank": record.rank,
            "team_name": record.team.name,
            "wins": record.win,
            "losses": record.loss,
            "ties": record.tie,
            "points_for": record.points_for,
            "points_against": record.points_against,
            "win_pct": record.win_percentage,
            "streak": record.streak,
        })
    return pd.DataFrame(rows)


def get_rosters_df(league: League) -> pd.DataFrame:
    rows = []
    for team in league.teams:  # teams is a list, not callable
        try:
            roster = league.team_roster(team.id)
            for row in roster.rows:
                if row.player is None:
                    continue
                player = row.player
                pos_str = re.sub(r"<[^>]+>", "", getattr(player, "pos_short_name", "") or "")
                rows.append({
                    "player_id": player.id,
                    "name": player.name,
                    "position": pos_str,
                    "slot": row.position.short_name,
                    "score": row.total_fantasy_points or 0,
                    "ppg": row.fantasy_points_per_game or 0,
                    "team_name": team.name,
                })
        except Exception:
            continue
    return pd.DataFrame(rows)


def get_scoring_periods(league: League) -> pd.DataFrame:
    rows = []
    # scoring_periods is a dict attribute, not a method
    for period_num, period in league.scoring_periods.items():
        rows.append({
            "period_num": period_num,
            "period_name": str(period),
            "range": getattr(period, "range", ""),
        })
    return pd.DataFrame(rows)


def get_scoring_period_results(league: League) -> pd.DataFrame:
    rows = []
    try:
        results = league.scoring_period_results()
        for period_num, result in results.items():
            for matchup in result.matchups:
                rows.append({
                    "period_num": period_num,
                    "home_team": matchup.home.name,
                    "home_score": matchup.home_score,
                    "away_team": matchup.away.name,
                    "away_score": matchup.away_score,
                })
    except Exception:
        pass
    return pd.DataFrame(rows)


def get_trade_block(league: League) -> pd.DataFrame:
    rows = []
    try:
        blocks = league.trade_block()  # returns list[TradeBlock]
        for block in blocks:
            for entry in block.players:
                rows.append({
                    "name": entry.player.name,
                    "position": re.sub(r"<[^>]+>", "", getattr(entry.player, "pos_short_name", "") or ""),
                    "owner_team": block.team.name,
                    "note": getattr(entry, "note", ""),
                })
    except Exception:
        pass
    return pd.DataFrame(rows)
