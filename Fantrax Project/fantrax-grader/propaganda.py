"""
Propaganda engine — finds bad news on opposing players and generates
over-the-top trash talk for your fantasy league group chat.
"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

# ── News fetching ─────────────────────────────────────────────────────────────

def _search_player_news(player_name: str) -> list[dict]:
    """Search Google News RSS for recent bad news on a player."""
    results = []
    query = f"{player_name} baseball injury slump struggling 2025 2026"
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.content, "xml")
        for item in soup.find_all("item")[:5]:
            title = item.find("title")
            link  = item.find("link")
            pub   = item.find("pubDate")
            if title:
                results.append({
                    "title": title.get_text(strip=True),
                    "link":  link.get_text(strip=True) if link else "",
                    "date":  pub.get_text(strip=True)[:16] if pub else "",
                })
    except Exception:
        pass
    return results


def _fetch_rotowire_news(player_name: str) -> str:
    """Try to grab the latest Rotowire blurb for a player."""
    try:
        last, first = player_name.split(" ", 1)[1], player_name.split(" ", 1)[0]
    except ValueError:
        last, first = player_name, ""
    slug = f"{first}-{last}".lower().replace(" ", "-").replace(".", "")
    url = f"https://www.rotowire.com/baseball/player/{slug}-1.htm"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, "lxml")
        blurb = soup.select_one(".player-news-item__blurb, .news-update")
        if blurb:
            return blurb.get_text(strip=True)[:300]
    except Exception:
        pass
    return ""


# ── Chirp generation ──────────────────────────────────────────────────────────

# Chirp templates — {name}, {team}, {stat}, {headline} slots
_CHIRP_TEMPLATES_BAD = [
    "🚨 BREAKING: {name} is cooked. Absolutely cooked. Pack it up, {team}.",
    "📉 {name} has the fantasy value of a wet napkin right now. Thoughts and prayers, {team}.",
    "⚰️ RIP {name}'s season. Gone too soon. {team} fans in shambles.",
    "🔥 {name} is so cold right now he's making your whole roster look like a dumpster fire, {team}.",
    "😬 {name} — the guy {team} is counting on — is out here looking like a AAAA player. Yikes.",
    "📰 HEADLINE: '{headline}' — {team}, your ace is a liability. Sleep tight.",
    "🗑️ {name} is the fantasy equivalent of a participation trophy. Congrats, {team}.",
    "💀 {name} is so bad right now that even his own highlights are embarrassing. {team} is cooked.",
    "🤡 {team} really out here rostering {name} like it's going to work out. Bold strategy.",
    "📊 Fun fact: {name}'s recent numbers are worse than a replacement-level player off the waiver wire. {team} is in trouble.",
]

_CHIRP_TEMPLATES_DECLINE = [
    "📉 {name} is 33 years old and declining faster than {team}'s playoff hopes.",
    "⏳ Father Time is undefeated, and {name} is losing badly. {team} is paying for nostalgia.",
    "🧓 {name} is out here collecting a roster spot like it's a pension. {team} deserves better.",
    "🪦 {name}'s dynasty value is in freefall. {team} is holding a bag of regrets.",
    "😂 {team} really built their team around {name} at age {age}? That's adorable.",
]

_CHIRP_TEMPLATES_INJURY = [
    "🏥 {name} is hurt AGAIN. {team}, your injury luck is a personality trait at this point.",
    "🩹 {name} is on the IL faster than {team} can make excuses. Classic.",
    "😤 {name} can't stay healthy and {team} can't stop rostering him. A love story.",
    "🚑 {name} is basically a part-time player at this point. {team} is paying full-time prices.",
]

_CHIRP_TEMPLATES_GOOD = [
    "👀 Meanwhile, {name} on {team} is quietly having a disaster of a season. Don't look now.",
    "🤫 {team} is hoping nobody notices that {name} is their 'ace' right now. We noticed.",
]

import random

def _pick_chirp(player_name: str, team: str, age: int, headlines: list[str], grade: str) -> str:
    headline = headlines[0] if headlines else f"{player_name} struggles to find form"
    # Shorten headline
    headline = headline[:80] + "..." if len(headline) > 80 else headline

    ctx = {"name": player_name, "team": team, "age": age,
           "headline": headline, "stat": ""}

    # Pick template pool based on context
    if any(w in headline.lower() for w in ["injur", "il ", "disabled", "strain", "surgery", "hurt"]):
        pool = _CHIRP_TEMPLATES_INJURY
    elif age and age >= 32:
        pool = _CHIRP_TEMPLATES_DECLINE
    elif grade in ("D+", "D", "F"):
        pool = _CHIRP_TEMPLATES_BAD
    else:
        pool = _CHIRP_TEMPLATES_BAD + _CHIRP_TEMPLATES_GOOD

    template = random.choice(pool)
    return template.format(**ctx)


# ── Main entry point ──────────────────────────────────────────────────────────

def build_propaganda(graded_df, my_team: str, top_n: int = 8) -> list[dict]:
    """
    Finds the most chirp-worthy players on opposing teams and returns
    a list of propaganda dicts with player info + generated chirp.

    Targets:
      - Low-grade players (D/F) on other teams
      - High-age players with declining grades
      - Any player with recent bad news headlines
    """
    import pandas as pd

    others = graded_df[graded_df["team_name"] != my_team].copy()

    # Score "chirpability": low grade + old age = maximum propaganda value
    grade_score = {"F": 10, "D": 9, "D+": 8, "C-": 6, "C": 5, "C+": 4,
                   "B-": 2, "B": 1, "B+": 0, "A-": 0, "A": 0, "A+": 0}
    others["chirp_score"] = (
        others["grade"].map(grade_score).fillna(0) +
        others["age"].apply(lambda a: max(0, (int(a) - 30) * 1.5) if pd.notna(a) else 0)
    )

    targets = others.nlargest(top_n, "chirp_score")

    results = []
    for _, row in targets.iterrows():
        name  = row["name"]
        team  = row["team_name"]
        age   = int(row["age"]) if pd.notna(row.get("age")) else None
        grade = row.get("grade", "?")
        grade_pct = row.get("grade_pct", 0)
        pos   = row.get("position", "")
        weighted = row.get("weighted_fpts", 0)
        proj  = row.get("fpts_proj", 0)

        # Fetch news
        news = _search_player_news(name)
        headlines = [n["title"] for n in news]

        chirp = _pick_chirp(name, team, age, headlines, grade)

        results.append({
            "name": name,
            "team": team,
            "position": pos,
            "age": age,
            "grade": grade,
            "grade_pct": round(float(grade_pct), 1),
            "weighted_fpts": round(float(weighted), 1),
            "proj_fpts": round(float(proj), 1) if proj else 0,
            "chirp": chirp,
            "headlines": headlines[:3],
            "chirp_score": round(float(row["chirp_score"]), 1),
        })

    return results
