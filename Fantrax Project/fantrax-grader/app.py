"""
Streamlit app — Fantrax Fantasy Baseball Grader & Trade Recommender
Run: python -m streamlit run app.py
"""
import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

import auth  # noqa: F401
from scraper import get_league, get_standings, get_rosters_df, get_scoring_period_results, get_trade_block
from dynasty import apply_dynasty_value
from fantrax_history import fetch_all_seasons, compute_weighted_fpts
from grader import grade_players, rank_players
from recommender import recommend_trades
from prospects import get_available_prospects

st.set_page_config(page_title="Baseball Neard", page_icon="⚾", layout="wide")

# ── Global styles ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Center all dataframe column headers */
[data-testid="stDataFrame"] th {
    text-align: center !important;
}
[data-testid="stDataFrame"] td {
    text-align: center !important;
}
/* Tab styling */
[data-testid="stTabs"] button {
    font-weight: 600;
    font-size: 0.9rem;
}
/* Metric cards */
[data-testid="stMetric"] {
    background: #0e1e2e;
    border-radius: 8px;
    padding: 8px 12px;
    border: 1px solid #1e3a52;
}
/* Sidebar */
[data-testid="stSidebar"] {
    background: #0a1520;
}
/* Green primary button */
div[data-testid="stButton"] button[kind="primary"] {
    background-color: #1a7a1a !important;
    border-color: #1a7a1a !important;
    color: white !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover {
    background-color: #2e8b2e !important;
    border-color: #2e8b2e !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    "<h1 style='text-align:center;font-size:2.8rem;font-weight:900;"
    "letter-spacing:4px;color:#ffffff;margin-bottom:4px'>⚾ BASEBALL NEARD</h1>"
    "<p style='text-align:center;color:#7eb8e8;font-size:0.85rem;margin-top:0'>"
    "Dynasty · Statcast · Trade Intelligence</p>",
    unsafe_allow_html=True,
)

# ── Column display name maps ──────────────────────────────────────────────────

GRADE_COL_NAMES = {
    "rank": "Rank", "name": "Player", "position": "Pos", "pos_group": "Group",
    "team_name": "Team", "slot": "Slot", "age": "Age", "score": "Current FPts",
    "ppg": "FP/G", "age_multiplier": "Age Mult", "dynasty_score": "Dynasty Score",
    "scarcity_mult": "Scarcity", "value_score": "Value Score",
    "savant_score": "Savant Score", "grade_pct": "Grade %", "grade": "Grade",
    "est_woba": "xwOBA", "barrel_batted_rate": "Barrel%",
    "sprint_speed": "Sprint Spd", "outs_above_average": "OAA",
    "xera": "xERA", "era": "ERA",
}

PROSPECT_COL_NAMES = {
    "consensus_rank": "Rank", "name": "Player", "position": "Pos", "org": "Org",
    "age": "Age", "milb_level": "Level", "ops": "OPS", "hr": "HR", "sb": "SB",
    "era": "ERA", "k9": "K/9", "production_score": "Production",
    "pedigree_score": "Pedigree", "level_age_score": "Lvl/Age",
    "age_multiplier": "Age Mult", "dynasty_value": "Dynasty Value",
    "available": "Available",
}

SAVANT_H_COL_NAMES = {
    "name": "Player", "player_id": "MLB ID", "pa": "PA",
    "savant_score": "Savant Score", "est_woba": "xwOBA",
    "barrel_batted_rate": "Barrel%", "sprint_speed": "Sprint Spd",
    "outs_above_average": "OAA",
}

SAVANT_P_COL_NAMES = {
    "name": "Player", "player_id": "MLB ID", "pa": "PA",
    "savant_score": "Savant Score", "est_woba": "xwOBA against",
    "xera": "xERA", "era": "ERA", "era_minus_xera_diff": "ERA - xERA",
}

def _rename(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    return df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})

def _round_df(df: pd.DataFrame, decimals: int = 2) -> pd.DataFrame:
    """Round all float columns to at most `decimals` places."""
    out = df.copy()
    for col in out.select_dtypes(include="float").columns:
        out[col] = out[col].round(decimals)
    return out

def _fix_age(df: pd.DataFrame) -> pd.DataFrame:
    """Cast Age column (or 'age') to nullable int so it displays without decimals."""
    int_cols = {"Age", "age", "HR", "hr", "SB", "sb", "AB", "ab", "Rank", "rank", "consensus_rank"}
    for col in int_cols:
        if col in df.columns:
            df = df.copy()
            df[col] = pd.to_numeric(df[col], errors="coerce").round(0).astype("Int64")
    return df

# Column format specs: col_name → format string for st.column_config.NumberColumn
_NUM_FMTS = {
    # Fantasy points — whole numbers
    "Current FPts": "%.0f", "FP/G": "%.1f", "Weighted FPts": "%.0f",
    "2026 Proj FPts": "%.0f", "2025 FPts": "%.0f", "2026 Proj": "%.0f",
    "2024 FPts": "%.0f",
    # Age — whole number
    "Age": "%.0f",
    # Grades / scores — 1 decimal
    "Grade %": "%.1f", "Dynasty Score": "%.1f", "Value Score": "%.1f",
    "Savant Score": "%.1f", "Production": "%.1f", "Pedigree": "%.1f",
    "Lvl/Age": "%.1f", "Dynasty Value": "%.1f",
    # Multipliers — 2 decimal
    "Age Mult": "%.2f", "Scarcity": "%.2f",
    # Savant / rate stats — 3 decimal
    "xwOBA": "%.3f", "xwOBA against": "%.3f",
    # Percentages — 1 decimal
    "Barrel%": "%.1f", "Sprint Spd": "%.1f", "OAA": "%.1f",
    "xERA": "%.2f", "ERA": "%.2f", "ERA - xERA": "%.2f",
    "OPS": "%.3f", "K/9": "%.2f",
    # Prospect scores
    "Win%": "%.3f",
}

def _col_config(df: pd.DataFrame) -> dict:
    """Build a column_config dict for all numeric columns in df."""
    import streamlit as st
    cfg = {}
    for col in df.columns:
        fmt = _NUM_FMTS.get(col)
        if fmt and col in df.select_dtypes(include="number").columns:
            cfg[col] = st.column_config.NumberColumn(col, format=fmt)
    return cfg


# ── MLB headshot helper ───────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def get_mlb_id_map() -> dict[str, int]:
    """Returns {lower_name: mlb_id} from MLB Stats API."""
    import requests
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/sports/1/players",
            params={"season": 2026}, timeout=15,
        )
        return {p["fullName"].lower(): p["id"] for p in resp.json().get("people", [])}
    except Exception:
        return {}

def player_headshot_url(player_name: str, mlb_id_map: dict) -> str | None:
    key = player_name.lower().strip()
    mlb_id = mlb_id_map.get(key)
    if not mlb_id:
        # fuzzy: first initial + last name
        parts = key.split()
        if len(parts) >= 2:
            last = parts[-1]
            first_init = parts[0][0]
            for k, v in mlb_id_map.items():
                kp = k.split()
                if kp and kp[-1] == last and kp[0][0] == first_init:
                    mlb_id = v
                    break
    if not mlb_id:
        return None
    return (
        f"https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"d_people:generic:headshot:67:current.png/w_213,q_auto:best/"
        f"v1/people/{mlb_id}/headshot/67/current"
    )


# ── Player Profile Dialog ─────────────────────────────────────────────────────

def open_profile(name: str):
    """Set session state to open the player profile dialog on next rerun."""
    st.session_state["_profile_player"] = name
    st.session_state["_profile_pending"] = True

@st.dialog("⚾ Player Profile", width="large")
def _render_player_profile(player_name: str, graded_df: pd.DataFrame,
                           history_df: pd.DataFrame,
                           savant_hitters: pd.DataFrame, savant_pitchers: pd.DataFrame,
                           mlb_id_map: dict,
                           league_session=None,
                           savant_pct_hitters: pd.DataFrame = None,
                           savant_pct_pitchers: pd.DataFrame = None):
    row = graded_df[graded_df["name"] == player_name]
    if row.empty:
        st.warning(f"No data found for {player_name}")
        return
    p = row.iloc[0]

    grade_colours = {
        "A+": "#1a7a1a", "A": "#2e8b2e", "A-": "#3d9e3d",
        "B+": "#5a8a00", "B": "#7a9e00", "B-": "#9ab000",
        "C+": "#c8a000", "C": "#d4880a", "C-": "#d46a0a",
        "D+": "#c84040", "D": "#b02020", "F": "#800000",
    }
    grade = p.get("grade", "?")
    grade_col = grade_colours.get(grade, "#555")
    age_val = p.get("age")
    age_str = str(int(age_val)) if pd.notna(age_val) else "—"

    img_url = player_headshot_url(player_name, mlb_id_map)
    h_img, h_info, h_grade, h_m1, h_m2 = st.columns([1, 3, 1, 1, 1])
    with h_img:
        if img_url:
            st.image(img_url, width=90)
        else:
            st.markdown("👤")
    with h_info:
        st.markdown(f"## {player_name}")
        st.caption(f"{p.get('position','?')} · {p.get('team_name','?')} · Age {age_str}")
    with h_grade:
        st.markdown(f"<h1 style='color:{grade_col};text-align:center'>{grade}</h1>", unsafe_allow_html=True)
        st.caption("Grade")
    with h_m1:
        st.metric("Grade Score", f"{p.get('grade_pct', 0):.1f}")
    with h_m2:
        st.metric("Age Mult", f"{p.get('age_multiplier', 1.0):.3f}")

    st.divider()

    hist_row = history_df[history_df["name"] == player_name] \
        if history_df is not None and not history_df.empty else pd.DataFrame()

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("#### 📊 Scoring History & Projections")
        if not hist_row.empty:
            h = hist_row.iloc[0]
            chart_data = {}
            if h.get("fpts_2024", 0): chart_data["2024"] = float(h["fpts_2024"])
            if h.get("fpts_2025", 0): chart_data["2025"] = float(h["fpts_2025"])
            if h.get("fpts_proj", 0): chart_data["2026 Proj"] = float(h["fpts_proj"])
            if chart_data:
                st.bar_chart(pd.DataFrame({"Season": list(chart_data.keys()),
                                           "Fantasy Points": list(chart_data.values())}).set_index("Season"),
                             color="#2e8b2e")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("2024 FPts",  f"{h.get('fpts_2024', 0):.0f}")
            m2.metric("2025 FPts",  f"{h.get('fpts_2025', 0):.0f}")
            m3.metric("2026 Proj",  f"{h.get('fpts_proj', 0):.0f}")
            m4.metric("Weighted",   f"{h.get('weighted_fpts', 0):.1f}")
            trend = float(h.get("fpts_2025", 0)) - float(h.get("fpts_2024", 0))
            if trend > 0:
                st.success(f"▲ Up {trend:+.0f} FPts from 2024 → 2025")
            elif trend < 0:
                st.warning(f"▼ Down {trend:+.0f} FPts from 2024 → 2025")
            drs = h.get("dynasty_rank_score")
            if drs is not None:
                st.metric("Dynasty Rank Score", f"{float(drs):.1f} / 100")
        else:
            st.info("No multi-year history available.")

        # ── Real MLB stats ────────────────────────────────────────────────────
        st.markdown("#### ⚾ 2025 MLB Stats")
        _mlb_id = mlb_id_map.get(player_name.lower().strip())
        if not _mlb_id:
            _parts = player_name.lower().split()
            if len(_parts) >= 2:
                _last, _fi = _parts[-1], _parts[0][0]
                for _k, _v in mlb_id_map.items():
                    _kp = _k.split()
                    if _kp and _kp[-1] == _last and _kp[0][0] == _fi:
                        _mlb_id = _v
                        break
        if _mlb_id:
            from player_details import fetch_mlb_stats
            _mlb = fetch_mlb_stats(_mlb_id, season=2025)
            if _mlb:
                if _mlb.get("type") == "hitter":
                    _c1, _c2, _c3, _c4 = st.columns(4)
                    _c1.metric("AVG",  _mlb.get("avg", "—"))
                    _c2.metric("OBP",  _mlb.get("obp", "—"))
                    _c3.metric("SLG",  _mlb.get("slg", "—"))
                    _c4.metric("OPS",  _mlb.get("ops", "—"))
                    _c5, _c6, _c7, _c8 = st.columns(4)
                    _c5.metric("HR",   str(_mlb.get("hr", "—")))
                    _c6.metric("RBI",  str(_mlb.get("rbi", "—")))
                    _c7.metric("SB",   str(_mlb.get("sb", "—")))
                    _c8.metric("G",    str(_mlb.get("games", "—")))
                    st.caption(f"K% {_mlb.get('k_pct','—')} · BB% {_mlb.get('bb_pct','—')} · {_mlb.get('ab','—')} AB")
                else:
                    _c1, _c2, _c3, _c4 = st.columns(4)
                    _c1.metric("ERA",  _mlb.get("era", "—"))
                    _c2.metric("WHIP", _mlb.get("whip", "—"))
                    _c3.metric("K/9",  _mlb.get("k9", "—"))
                    _c4.metric("BB/9", _mlb.get("bb9", "—"))
                    _c5, _c6, _c7, _c8 = st.columns(4)
                    _c5.metric("W",    str(_mlb.get("wins", "—")))
                    _c6.metric("L",    str(_mlb.get("losses", "—")))
                    _c7.metric("SV",   str(_mlb.get("saves", "—")))
                    _c8.metric("IP",   str(_mlb.get("ip", "—")))
                    st.caption(f"SO {_mlb.get('so','—')} · BB {_mlb.get('bb','—')} · {_mlb.get('games','—')} G")
            else:
                st.caption("No 2025 MLB stats found.")
        else:
            st.caption("MLB ID not found.")

        # ── Recent fantasy game log ───────────────────────────────────────────
        st.markdown("#### 🎮 Last 10 Fantasy Games")
        if league_session is not None:
            from player_details import fetch_recent_game_log
            _game_log = fetch_recent_game_log(player_name, "hp3gi9z9mg6wf2p7", league_session, n=10)
            if not _game_log.empty:
                def _color_fpts(val):
                    try:
                        v = float(val)
                        if v >= 30:  return "color:#2e8b2e;font-weight:bold"
                        if v >= 15:  return "color:#9ab000"
                        if v >= 0:   return "color:#888"
                        return "color:#c84040"
                    except Exception:
                        return ""
                st.dataframe(
                    _game_log.style.applymap(_color_fpts, subset=["FPts"]),
                    use_container_width=True, hide_index=True,
                )
                _avg = _game_log["FPts"].dropna().mean()
                st.caption(f"Avg over last {len(_game_log)} games: {_avg:.1f} FPts")
            else:
                st.caption("No recent game log available.")
        else:
            st.caption("Session unavailable.")

    with col_right:
        st.markdown("#### 🎯 Savant Stats")

        # Look up in hitters first, then pitchers
        def _find(df):
            if df is None or df.empty: return pd.DataFrame()
            m = df[df["name"].str.lower() == player_name.lower()]
            return m

        def _find_pct(pct_df, score_row):
            """Match percentile row by player_id first, then name."""
            if pct_df is None or pct_df.empty: return pd.DataFrame()
            if score_row is not None and not score_row.empty:
                pid = score_row.iloc[0].get("player_id")
                if pid and "player_id" in pct_df.columns:
                    m = pct_df[pct_df["player_id"] == pid]
                    if not m.empty: return m
            if "name" in pct_df.columns:
                return pct_df[pct_df["name"].str.lower() == player_name.lower()]
            return pd.DataFrame()

        h_row = _find(savant_hitters)
        p_row = _find(savant_pitchers)

        # Percentile chart helper — mirrors Baseball Savant's blue→white→red scale
        def _savant_colour(pct: float) -> str:
            """
            0   → deep blue  (#1a4fa0)
            50  → white      (#f0f0f0)
            100 → deep red   (#c0001a)
            Interpolates linearly through white in the middle.
            """
            pct = max(0.0, min(100.0, pct))
            if pct <= 50:
                t = pct / 50.0          # 0→1 as pct goes 0→50
                r = int(26  + t * (240 - 26))
                g = int(79  + t * (240 - 79))
                b = int(160 + t * (240 - 160))
            else:
                t = (pct - 50) / 50.0   # 0→1 as pct goes 50→100
                r = int(240 + t * (192 - 240))
                g = int(240 + t * (0   - 240))
                b = int(240 + t * (26  - 240))
            return f"rgb({r},{g},{b})"

        def _pct_bar(label: str, val):
            if val is None or pd.isna(val):
                return
            pct = float(val)
            colour = _savant_colour(pct)
            # Text is dark on light backgrounds (near 50), light on dark ends
            text_col = "#111" if 25 < pct < 75 else "#fff"
            bar_html = (
                f"<div style='margin-bottom:7px'>"
                f"<div style='display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px'>"
                f"<span style='color:#ccc'>{label}</span>"
                f"<span style='font-weight:bold;color:{colour}'>{pct:.0f}</span>"
                f"</div>"
                f"<div style='background:#2a2a2a;border-radius:4px;height:12px;position:relative'>"
                f"<div style='background:{colour};width:{pct:.0f}%;height:12px;border-radius:4px'></div>"
                f"</div></div>"
            )
            st.markdown(bar_html, unsafe_allow_html=True)

        if not h_row.empty:
            s = h_row.iloc[0]
            st.metric("Savant Score", f"{s.get('savant_score', 0):.1f} / 100")
            for label, col, fmt in [
                ("xwOBA",        "est_woba",            ".3f"),
                ("Barrel%",      "barrel_batted_rate",  ".1f"),
                ("Sprint Speed", "sprint_speed",        ".1f"),
                ("OAA",          "outs_above_average",  ".1f"),
            ]:
                val = s.get(col)
                if val is not None and pd.notna(val):
                    st.metric(label, f"{float(val):{fmt}}")

            # Percentile chart
            pct_row = _find_pct(savant_pct_hitters, h_row) if savant_pct_hitters is not None else pd.DataFrame()
            if not pct_row.empty:
                pr = pct_row.iloc[0]
                st.markdown("**Percentile Rankings**")
                HITTER_PCT_COLS = [
                    ("xwOBA",       "xwoba"),
                    ("xBA",         "xba"),
                    ("Barrel%",     "brl_percent"),
                    ("Exit Velo",   "exit_velocity"),
                    ("Hard Hit%",   "hard_hit_percent"),
                    ("Sprint Spd",  "sprint_speed"),
                    ("K%",          "k_percent"),
                    ("BB%",         "bb_percent"),
                    ("Whiff%",      "whiff_percent"),
                    ("OAA",         "oaa"),
                    ("Bat Speed",   "bat_speed"),
                ]
                # K%, Whiff%, Chase% — lower raw value = better for hitter, so invert display
                inverted = {"k_percent", "whiff_percent", "chase_percent"}
                for label, col in HITTER_PCT_COLS:
                    val = pr.get(col)
                    if val is not None and pd.notna(val):
                        display_pct = (100 - float(val)) if col in inverted else float(val)
                        _pct_bar(label, display_pct)
                # Link to full Savant page
                pid = pr.get("player_id")
                if pid:
                    st.markdown(f"[View full Savant page ↗](https://baseballsavant.mlb.com/savant-player/{int(pid)})", unsafe_allow_html=False)

        elif not p_row.empty:
            s = p_row.iloc[0]
            st.metric("Savant Score", f"{s.get('savant_score', 0):.1f} / 100")
            for label, col, fmt in [
                ("xwOBA Against",  "est_woba",              ".3f"),
                ("xERA",           "xera",                  ".2f"),
                ("ERA",            "era",                   ".2f"),
                ("ERA - xERA",     "era_minus_xera_diff",   ".2f"),
            ]:
                val = s.get(col)
                if val is not None and pd.notna(val):
                    st.metric(label, f"{float(val):{fmt}}")

            # Percentile chart
            pct_row = _find_pct(savant_pct_pitchers, p_row) if savant_pct_pitchers is not None else pd.DataFrame()
            if not pct_row.empty:
                pr = pct_row.iloc[0]
                st.markdown("**Percentile Rankings**")
                PITCHER_PCT_COLS = [
                    ("xwOBA Against", "xwoba"),
                    ("xBA Against",   "xba"),
                    ("xERA",          "xera"),
                    ("Barrel% Alwd",  "brl_percent"),
                    ("Exit Velo Alwd","exit_velocity"),
                    ("Hard Hit% Alwd","hard_hit_percent"),
                    ("K%",            "k_percent"),
                    ("BB%",           "bb_percent"),
                    ("Whiff%",        "whiff_percent"),
                    ("Chase%",        "chase_percent"),
                    ("FB Velo",       "fb_velocity"),
                    ("FB Spin",       "fb_spin"),
                    ("Curve Spin",    "curve_spin"),
                ]
                # For pitchers the CSV already encodes higher = better for all metrics
                for label, col in PITCHER_PCT_COLS:
                    val = pr.get(col)
                    if val is not None and pd.notna(val):
                        _pct_bar(label, float(val))
                pid = pr.get("player_id")
                if pid:
                    st.markdown(f"[View full Savant page ↗](https://baseballsavant.mlb.com/savant-player/{int(pid)})")
        else:
            st.info("No Savant data available.")

        st.markdown("#### 🏆 Dynasty Value")
        d1, d2 = st.columns(2)
        d1.metric("Dynasty Score", f"{p.get('dynasty_score', 0):.1f}")
        d2.metric("Value Score",   f"{p.get('value_score', 0):.1f}")
        st.metric("Scarcity Mult", f"{p.get('scarcity_mult', 1.0):.1f}x")


# ── Load data ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Fetching league data...")
def load_data():
    league = get_league()
    def _standings(): return get_standings(league)
    def _rosters():   return get_rosters_df(league)
    def _scoring():   return get_scoring_period_results(league)
    def _trade():     return get_trade_block(league)
    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_standings): "standings", ex.submit(_rosters): "rosters",
                   ex.submit(_scoring): "scoring", ex.submit(_trade): "trade"}
        for f in as_completed(futures):
            key = futures[f]
            try:    results[key] = f.result()
            except Exception as e:
                print(f"  {key} fetch error: {e}")
                results[key] = pd.DataFrame()
    return results["standings"], results["rosters"], results["scoring"], results["trade"], league.session

@st.cache_data(ttl=3600, show_spinner="Fetching multi-year scoring history...")
def load_history(_session, league_id):
    return fetch_all_seasons(_session, league_id)

@st.cache_data(ttl=3600, show_spinner="Fetching Savant data...")
def load_savant():
    from savant import build_hitter_savant_scores, build_pitcher_savant_scores, fetch_percentile_rankings
    with ThreadPoolExecutor(max_workers=4) as ex:
        fh  = ex.submit(build_hitter_savant_scores)
        fp  = ex.submit(build_pitcher_savant_scores)
        fph = ex.submit(fetch_percentile_rankings, "batter")
        fpp = ex.submit(fetch_percentile_rankings, "pitcher")
        return fh.result(), fp.result(), fph.result(), fpp.result()

@st.cache_data(ttl=600, show_spinner="Fetching prospect rankings...")
def load_prospects(_session, league_id, rostered_names_tuple):
    return get_available_prospects(league_id, _session, set(rostered_names_tuple))

try:
    standings_df, rosters_df, scoring_df, trade_block_df, league_session = load_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

with st.spinner("Loading scoring history & Savant data..."):
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_history = ex.submit(load_history, league_session, "hp3gi9z9mg6wf2p7")
        f_savant  = ex.submit(load_savant)
        history_raw = f_history.result()
        savant_hitters, savant_pitchers, savant_pct_hitters, savant_pct_pitchers = f_savant.result()

mlb_id_map = get_mlb_id_map()


# ── Sidebar ───────────────────────────────────────────────────────────────────

# ── Dynasty weight defaults in session state ──────────────────────────────────
for _k, _v in [("w_proj",35),("w_2025",25),("w_2024",20),("w_dynasty",10),("w_trend",10)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Single popover above the tabs — sliders only rendered once
with st.popover("⚖️ Dynasty Score Weights"):
    st.caption("Values auto-normalize to 100%.")
    st.slider("2026 Projections",    0, 100, key="w_proj",    step=5)
    st.slider("2025 Actuals",        0, 100, key="w_2025",    step=5)
    st.slider("2024 Actuals",        0, 100, key="w_2024",    step=5)
    st.slider("Dynasty Rankings",    0, 100, key="w_dynasty", step=5)
    st.slider("Recency Trend Bonus", 0, 100, key="w_trend",   step=5)
    _pt = st.session_state.w_proj + st.session_state.w_2025 + st.session_state.w_2024 + st.session_state.w_dynasty + st.session_state.w_trend or 100
    st.caption(
        f"proj {st.session_state.w_proj/_pt:.0%} · "
        f"2025 {st.session_state.w_2025/_pt:.0%} · "
        f"2024 {st.session_state.w_2024/_pt:.0%} · "
        f"dynasty {st.session_state.w_dynasty/_pt:.0%} · "
        f"trend {st.session_state.w_trend/_pt:.0%}"
    )

_total = st.session_state.w_proj + st.session_state.w_2025 + st.session_state.w_2024 + st.session_state.w_dynasty + st.session_state.w_trend or 100
_nw_proj    = st.session_state.w_proj    / _total
_nw_2025    = st.session_state.w_2025    / _total
_nw_2024    = st.session_state.w_2024    / _total
_nw_dynasty = st.session_state.w_dynasty / _total
_nw_trend   = st.session_state.w_trend   / _total

# Recompute grades from weights
history_df = compute_weighted_fpts(
    history_raw, w_proj=_nw_proj, w_2025=_nw_2025, w_2024=_nw_2024,
    w_dynasty=_nw_dynasty, w_trend=_nw_trend,
) if not history_raw.empty else history_raw

rosters_df = apply_dynasty_value(rosters_df.drop(
    columns=[c for c in ["weighted_fpts","dynasty_score","age_multiplier","scarcity_mult",
                         "fpts_2024","fpts_2025","fpts_proj","fpg_proj","dynasty_rank_score"]
             if c in rosters_df.columns], errors="ignore"), history_df)

_savant_parts = [df for df in [savant_hitters, savant_pitchers] if not df.empty]
savant_combined = pd.concat(_savant_parts, ignore_index=True).drop_duplicates("name", keep="first") \
    if _savant_parts else pd.DataFrame()

graded_df = grade_players(rosters_df, savant_df=savant_combined)

_all_names = sorted(graded_df["name"].dropna().unique().tolist())

# ── Top-of-page quick search ──────────────────────────────────────────────────
_qs_col, _qs_spacer = st.columns([2, 5])
with _qs_col:
    _qs = st.selectbox(
        "🔍 Search any player",
        options=[""] + _all_names,
        index=0,
        key="top_search",
    )
if _qs and _qs != st.session_state.get("_last_top_search"):
    st.session_state["_last_top_search"] = _qs
    open_profile(_qs)
    st.rerun()


# ── Shared helpers ────────────────────────────────────────────────────────────

def colour_grade(val):
    colours = {"A+": "#1a7a1a", "A": "#2e8b2e", "A-": "#3d9e3d",
               "B+": "#5a8a00", "B": "#7a9e00", "B-": "#9ab000",
               "C+": "#c8a000", "C": "#d4880a", "C-": "#d46a0a",
               "D+": "#c84040", "D": "#b02020", "F": "#800000"}
    return f"color: {colours.get(val, '#555')}; font-weight: bold"

def _clickable_player_list(names: list[str], key_prefix: str):
    """Renders a compact grid of clickable player name buttons."""
    cols = st.columns(5)
    for i, name in enumerate(names):
        if cols[i % 5].button(name, key=f"{key_prefix}_{i}", use_container_width=True):
            open_profile(name)

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Standings", "🏅 Player Grades", "🔄 Trade Recommender",
    "🌱 Prospect Wire", "🎯 Savant Stats", "⚖️ Trade Grader",
])

# ── Tab 1: Standings ──────────────────────────────────────────────────────────
with tab1:
    st_actual, st_proj = st.tabs(["📋 Current Standings", "🔮 Projected Standings"])

    with st_actual:
        st.subheader("🏆 League Standings")
        display_standings = standings_df.sort_values("rank").rename(columns={
            "rank": "Rank", "team_name": "Team", "wins": "W", "losses": "L",
            "ties": "T", "points_for": "Pts For", "points_against": "Pts Against",
            "win_pct": "Win%", "streak": "Streak",
        })
        st.dataframe(_round_df(display_standings), use_container_width=True, hide_index=True,
                     column_config=_col_config(display_standings))

    with st_proj:
        st.subheader("🔮 Projected Standings")
        st.caption(
            f"Weighted FPts per roster — proj {_nw_proj:.0%} · 2025 {_nw_2025:.0%} · "
            f"2024 {_nw_2024:.0%} · dynasty {_nw_dynasty:.0%} · trend {_nw_trend:.0%}"
        )
        proj_cols = ["name", "team_name", "position", "fpts_proj", "fpts_2025", "fpts_2024", "weighted_fpts", "grade"]
        roster_proj = rosters_df[[c for c in proj_cols if c in rosters_df.columns]].copy()
        team_proj = (
            roster_proj.groupby("team_name")
            .agg(total_weighted_fpts=("weighted_fpts","sum"),
                 total_proj_fpts=("fpts_proj","sum") if "fpts_proj" in roster_proj.columns else ("weighted_fpts","sum"),
                 total_2025_fpts=("fpts_2025","sum") if "fpts_2025" in roster_proj.columns else ("weighted_fpts","sum"),
                 roster_size=("weighted_fpts","count"))
            .reset_index()
        )
        team_proj = team_proj.sort_values("total_weighted_fpts", ascending=False).reset_index(drop=True)
        team_proj.index += 1
        team_proj.index.name = "proj_rank"
        team_proj = team_proj.reset_index()
        team_proj = team_proj.merge(standings_df[["team_name","rank","wins","losses","win_pct"]], on="team_name", how="left")
        team_proj["rank_change"] = (team_proj["rank"] - team_proj["proj_rank"]).apply(
            lambda x: f"▲ {int(x)}" if x > 0 else (f"▼ {int(abs(x))}" if x < 0 else "—"))
        team_proj = team_proj.rename(columns={
            "proj_rank": "Proj Rank", "team_name": "Team",
            "total_weighted_fpts": "Weighted FPts", "total_proj_fpts": "2026 Proj FPts",
            "total_2025_fpts": "2025 FPts", "roster_size": "Roster Size",
            "rank": "Current Rank", "wins": "W", "losses": "L", "win_pct": "Win%",
            "rank_change": "Movement",
        })
        for col in ["Weighted FPts", "2026 Proj FPts", "2025 FPts"]:
            if col in team_proj.columns:
                team_proj[col] = team_proj[col].round(1)
        disp_cols = [c for c in ["Proj Rank","Team","Weighted FPts","2026 Proj FPts","2025 FPts",
                                  "Roster Size","Current Rank","W","L","Win%","Movement"] if c in team_proj.columns]
        def _colour_movement(val):
            if isinstance(val, str):
                if val.startswith("▲"): return "color: #2e8b2e; font-weight: bold"
                if val.startswith("▼"): return "color: #c84040; font-weight: bold"
            return "color: #888"
        st.dataframe(team_proj[disp_cols].style.applymap(_colour_movement, subset=["Movement"]),
                     use_container_width=True, hide_index=True,
                     column_config=_col_config(team_proj[disp_cols]))
        st.markdown("#### Top Players by Team")
        for _, row in team_proj.iterrows():
            team = row["Team"]
            top5 = roster_proj[roster_proj["team_name"] == team].sort_values("weighted_fpts", ascending=False).head(5)
            with st.expander(f"{team} — Proj #{row['Proj Rank']}"):
                show_cols = [c for c in ["name","position","weighted_fpts","fpts_proj","grade"] if c in top5.columns]
                disp = top5[show_cols].rename(columns={"name":"Player","position":"Pos",
                    "weighted_fpts":"Weighted FPts","fpts_proj":"2026 Proj","grade":"Grade"})
                st.dataframe(disp.reset_index(drop=True), use_container_width=True, hide_index=True)


# ── Tab 2: Player Grades ──────────────────────────────────────────────────────
with tab2:
    st.subheader("🏅 Player Grades — Dynasty Adjusted")
    st.caption(
        f"Weighted FPts: proj {_nw_proj:.0%} · 2025 {_nw_2025:.0%} · "
        f"2024 {_nw_2024:.0%} · dynasty {_nw_dynasty:.0%} · trend {_nw_trend:.0%} "
        f"— × age multiplier × scarcity · blended 80% dynasty + 20% Savant"
    )
    position_filter = st.selectbox(
        "🔎 Filter by position",
        options=["All"] + sorted(rosters_df["position"].dropna().unique()),
        key="position_filter_tab2",
    )
    pos = None if position_filter == "All" else position_filter
    ranked = rank_players(graded_df, pos)

    display_ranked = _fix_age(_round_df(_rename(ranked, GRADE_COL_NAMES)))
    show_grade_cols = [c for c in ["Rank","Player","Pos","Team","Age","Grade","Grade %",
                                    "Dynasty Score","Value Score","Savant Score",
                                    "xwOBA","Barrel%","Sprint Spd","OAA","xERA","ERA",
                                    "Age Mult","Scarcity","FP/G"] if c in display_ranked.columns]
    sel = st.dataframe(
        display_ranked[show_grade_cols].style.applymap(colour_grade, subset=["Grade"]),
        use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config=_col_config(display_ranked[show_grade_cols]),
    )
    if sel and sel.selection.rows:
        _sel_name = ranked.iloc[sel.selection.rows[0]]["name"]
        if _sel_name != st.session_state.get("_last_grade_sel"):
            st.session_state["_last_grade_sel"] = _sel_name
            open_profile(_sel_name)
    elif not sel or not sel.selection.rows:
        st.session_state.pop("_last_grade_sel", None)


# ── Tab 3: Trade Recommender ──────────────────────────────────────────────────
with tab3:
    my_team = st.selectbox(
        "🏟️ Your team",
        options=sorted(rosters_df["team_name"].unique()),
        key="my_team_select",
    )
    st.subheader(f"🔄 Trade Recommender — {my_team}")

    INTENT_OPTIONS = [
        "🎲 Random",
        "🔨 Rebuild",
        "🏆 Win Now",
        "📈 Value Grab",
        "📦 Depth Add",
        "⭐ Consolidate",
        "🔄 Lateral",
    ]
    INTENT_DESCRIPTIONS = {
        "🎲 Random":     "Show me anything — surprise me",
        "🔨 Rebuild":    "Get younger, stock prospects, trade veterans for futures",
        "🏆 Win Now":    "Acquire proven contributors, push for a title this year",
        "📈 Value Grab": "Find undervalued players — buy low, win the trade",
        "📦 Depth Add":  "Turn one piece into multiple contributors",
        "⭐ Consolidate":"Package depth to land a star",
        "🔄 Lateral":    "Even swap — upgrade a position without losing value",
    }

    ic1, ic2, ic3 = st.columns([3, 1, 1], vertical_alignment="bottom")
    with ic1:
        trade_intent = st.selectbox(
            "What kind of trade are you looking for?",
            options=INTENT_OPTIONS,
            index=0,
            key="trade_intent_select",
        )
    with ic2:
        find_trades = st.button("🔍 Find Trades", use_container_width=True, type="primary")
    with ic3:
        random_trades = st.button("🎲 Random", use_container_width=True)
    st.caption(INTENT_DESCRIPTIONS.get(trade_intent, ""))

    # Determine effective intent
    effective_intent = "🎲 Random" if random_trades else trade_intent

    # Only run when button pressed OR intent already stored in session
    _trade_key = f"_trades_{my_team}_{effective_intent}"
    if find_trades or random_trades:
        st.session_state["_trade_results_key"] = _trade_key
        st.session_state[_trade_key] = None  # force refresh

    _active_results_key = st.session_state.get("_trade_results_key")
    proposals = st.session_state.get(_active_results_key) if _active_results_key else None

    if proposals is None and st.session_state.get("_trade_results_key"):
        active_key = st.session_state["_trade_results_key"]        # Extract intent from key: format is _trades_{team}_{intent}
        _key_parts = active_key.split("_trades_", 1)
        active_intent = _key_parts[1].split("_", 1)[1] if len(_key_parts) > 1 and "_" in _key_parts[1] else effective_intent
        with st.spinner(f"Finding {active_intent} trades..."):
            try:
                proposals = recommend_trades(graded_df, my_team, max_proposals=10, trade_intent=active_intent)
                st.session_state[active_key] = proposals
            except Exception as e:
                st.error(f"Trade recommender error: {e}")
                import traceback
                st.code(traceback.format_exc())
                proposals = []
    else:
        active_intent = effective_intent

    if proposals is None:
        st.info("👆 Select a trade type and hit **Find Trades** to get started.")
    elif not proposals:
        st.warning(f"No **{active_intent}** trades found. Try a different type or loosen your roster.")
        from recommender import _tradeable, _targetable, MAX_1FOR1_GAP, MAX_MULTI_GAP
        my_t = _tradeable(graded_df, my_team)
        with st.expander("🔍 Debug — why no trades?"):
            st.write(f"My tradeable players: {len(my_t)}")
            if not my_t.empty:
                st.dataframe(my_t[["name","position","grade_pct"]].head(10), hide_index=True)
            other_teams = [t for t in graded_df["team_name"].unique() if t != my_team]
            for ot in other_teams[:3]:
                tgt = _targetable(graded_df, ot)
                st.write(f"**{ot}** — targetable: {len(tgt)}")
                if not tgt.empty:
                    st.dataframe(tgt[["name","position","grade_pct"]].head(5), hide_index=True)
                    if not my_t.empty:
                        best = min(
                            abs(r["grade_pct"] - g["grade_pct"])
                            for _, r in tgt.iterrows()
                            for _, g in my_t.iterrows()
                        )
                        st.write(f"Closest 1-for-1 gap vs {ot}: **{best:.1f}** (limit={MAX_1FOR1_GAP})")
        st.success("Your roster looks balanced — no obvious trades right now.")
    else:
        st.caption(f"Found {len(proposals)} {active_intent} proposals.")
        for i, p in enumerate(proposals, 1):
            give_str = " + ".join(f"{g['name']} ({g['position']}, {g['grade']})" for g in p["give"])
            recv_str = " + ".join(f"{r['name']} ({r['position']}, {r['grade']})" for r in p["receive"])
            net = p["net_gain"]
            net_str = f"{'+' if net >= 0 else ''}{net}"
            net_color = "#2e8b2e" if net >= 0 else "#c84040"
            intent = p.get("intent", "")
            intent_tip = p.get("intent_tip", "")
            label = f"{intent} #{i} [{p['trade_type']}]  {give_str}  →  {recv_str}  |  Net: {net_str}"
            with st.expander(label):
                st.caption(f"{intent} — {intent_tip}")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**📤 {my_team} gives**")
                    for g in p["give"]:
                        sv = f" · Savant {g['savant_score']:.0f}" if g.get("savant_score") else ""
                        st.write(f"• **{g['name']}** — {g['position']}, Age {g['age']}, Grade **{g['grade']}** ({g['grade_pct']:.1f}){sv}")
                        if st.button(f"👤 {g['name']}", key=f"trade_give_{i}_{g['name']}"):
                            open_profile(g['name'])
                    st.metric("Give Total", f"{p['give_total']:.1f}")
                with col2:
                    st.markdown(f"**📥 {p['other_team']} gives**")
                    for r in p["receive"]:
                        sv = f" · Savant {r['savant_score']:.0f}" if r.get("savant_score") else ""
                        st.write(f"• **{r['name']}** — {r['position']}, Age {r['age']}, Grade **{r['grade']}** ({r['grade_pct']:.1f}){sv}")
                        if st.button(f"👤 {r['name']}", key=f"trade_recv_{i}_{r['name']}"):
                            open_profile(r['name'])
                    st.metric("Receive Total", f"{p['receive_total']:.1f}")

                st.markdown(f"<p style='text-align:center;font-size:1.1rem'>Net value: <span style='color:{net_color};font-weight:bold'>{net_str}</span></p>", unsafe_allow_html=True)

                # ── Trade breakdown button ────────────────────────────────────
                if st.button(f"📊 Why this trade works", key=f"breakdown_{i}"):
                    st.session_state[f"_show_breakdown_{i}"] = not st.session_state.get(f"_show_breakdown_{i}", False)

                if st.session_state.get(f"_show_breakdown_{i}", False):
                    st.divider()

                    # Pre-compute shared values
                    all_in_trade = p["give"] + p["receive"]
                    give_avg_age = sum(float(g.get("age") or 27) for g in p["give"]) / len(p["give"])
                    recv_avg_age = sum(float(r.get("age") or 27) for r in p["receive"]) / len(p["receive"])
                    give_avg_grade = p["give_total"] / len(p["give"])
                    recv_avg_grade = p["receive_total"] / len(p["receive"])
                    other_team = p["other_team"]

                    # Pull FPts from history_df for each player
                    def _fpts(name, col="fpts_2025"):
                        if history_df is None or history_df.empty: return 0
                        row = history_df[history_df["name"].str.lower() == name.lower()]
                        return float(row.iloc[0].get(col, 0)) if not row.empty else 0

                    def _team_avg_fpts(team):
                        t = graded_df[graded_df["team_name"] == team]
                        return float(t["score"].mean()) if not t.empty and "score" in t.columns else 0

                    # ── Row 1: compact metrics ────────────────────────────────
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Net Value", f"{net_str}", help="Grade % gained/lost")
                    m2.metric("Avg Age → You", f"{recv_avg_age:.0f}", delta=f"{recv_avg_age - give_avg_age:+.0f} yrs")
                    m3.metric("Avg Age → Them", f"{give_avg_age:.0f}", delta=f"{give_avg_age - recv_avg_age:+.0f} yrs")
                    m4.metric("Players Out", str(len(p["give"])))
                    m5.metric("Players In", str(len(p["receive"])))

                    # ── Row 2: FPts + Age side-by-side mini charts ────────────
                    ch1, ch2 = st.columns(2)

                    with ch1:
                        st.caption("📅 2025 Fantasy Points")
                        fpts_rows = []
                        for g in p["give"]:
                            fpts_rows.append({"Player": g["name"].split()[-1], "FPts": _fpts(g["name"]), "Side": "Out"})
                        for r in p["receive"]:
                            fpts_rows.append({"Player": r["name"].split()[-1], "FPts": _fpts(r["name"]), "Side": "In"})
                        fpts_df = pd.DataFrame(fpts_rows)
                        # Color: red for out, green for in via HTML bars
                        for _, row in fpts_df.iterrows():
                            color = "#c84040" if row["Side"] == "Out" else "#2e8b2e"
                            pct = min(int(row["FPts"] / 600 * 100), 100)
                            st.markdown(
                                f"<div style='margin-bottom:5px'>"
                                f"<div style='display:flex;justify-content:space-between;font-size:11px'>"
                                f"<span style='color:#ccc'>{row['Player']}</span>"
                                f"<span style='color:{color};font-weight:bold'>{row['FPts']:.0f}</span></div>"
                                f"<div style='background:#1e1e1e;border-radius:3px;height:8px'>"
                                f"<div style='background:{color};width:{pct}%;height:8px;border-radius:3px'></div>"
                                f"</div></div>",
                                unsafe_allow_html=True,
                            )

                    with ch2:
                        st.caption("🎂 Age Profile")
                        for g in p["give"]:
                            age = float(g.get("age") or 27)
                            pct = max(0, min(100, int((35 - age) / 15 * 100)))
                            st.markdown(
                                f"<div style='margin-bottom:5px'>"
                                f"<div style='display:flex;justify-content:space-between;font-size:11px'>"
                                f"<span style='color:#c84040'>{g['name'].split()[-1]} (out)</span>"
                                f"<span style='color:#c84040;font-weight:bold'>Age {age:.0f}</span></div>"
                                f"<div style='background:#1e1e1e;border-radius:3px;height:8px'>"
                                f"<div style='background:#c84040;width:{pct}%;height:8px;border-radius:3px'></div>"
                                f"</div></div>",
                                unsafe_allow_html=True,
                            )
                        for r in p["receive"]:
                            age = float(r.get("age") or 27)
                            pct = max(0, min(100, int((35 - age) / 15 * 100)))
                            st.markdown(
                                f"<div style='margin-bottom:5px'>"
                                f"<div style='display:flex;justify-content:space-between;font-size:11px'>"
                                f"<span style='color:#2e8b2e'>{r['name'].split()[-1]} (in)</span>"
                                f"<span style='color:#2e8b2e;font-weight:bold'>Age {age:.0f}</span></div>"
                                f"<div style='background:#1e1e1e;border-radius:3px;height:8px'>"
                                f"<div style='background:#2e8b2e;width:{pct}%;height:8px;border-radius:3px'></div>"
                                f"</div></div>",
                                unsafe_allow_html=True,
                            )

                    st.divider()

                    # ── Row 3: written case for each side ─────────────────────
                    # Pre-compute positional averages before splitting columns
                    league_pos_avg = graded_df.groupby("position")["score"].mean()
                    my_pos_avg = graded_df[graded_df["team_name"] == my_team].groupby("position")["score"].mean()
                    their_pos_avg = graded_df[graded_df["team_name"] == other_team].groupby("position")["score"].mean()
                    my_weak = [pos for pos in my_pos_avg.index if pos in league_pos_avg.index and my_pos_avg[pos] < league_pos_avg[pos]]
                    their_weak = [pos for pos in their_pos_avg.index if pos in league_pos_avg.index and their_pos_avg[pos] < league_pos_avg[pos]]
                    give_fpts = sum(_fpts(g["name"]) for g in p["give"])
                    recv_fpts = sum(_fpts(r["name"]) for r in p["receive"])

                    bc1, bc2 = st.columns(2)

                    with bc1:
                        st.markdown(f"**🏠 Why {my_team} does this**")
                        if net >= 0:
                            st.write(f"📈 Gains **{net:.1f}** grade pts in raw value")
                        if recv_avg_age < give_avg_age - 0.5:
                            st.write(f"🧒 Gets younger — {give_avg_age:.0f} → {recv_avg_age:.0f} avg age")
                        if len(p["receive"]) > len(p["give"]):
                            st.write(f"📦 Turns {len(p['give'])} into {len(p['receive'])} — adds depth")
                        if recv_avg_grade > give_avg_grade:
                            st.write(f"⭐ Avg player quality up: {give_avg_grade:.1f} → {recv_avg_grade:.1f}")
                        recv_pos = [r["position"] for r in p["receive"]]
                        fits = [pos for pos in recv_pos if pos in my_weak]
                        if fits:
                            st.write(f"🎯 Fills weak spot(s): **{', '.join(set(fits))}**")
                        if recv_fpts > give_fpts:
                            st.write(f"📊 More 2025 FPts coming in ({recv_fpts:.0f} vs {give_fpts:.0f})")

                    with bc2:
                        st.markdown(f"**🏠 Why {other_team} does this**")
                        if net <= 0:
                            st.write(f"📈 Gains **{abs(net):.1f}** grade pts in raw value")
                        if give_avg_age < recv_avg_age - 0.5:
                            st.write(f"🧒 Gets younger — {recv_avg_age:.0f} → {give_avg_age:.0f} avg age")
                        if len(p["give"]) > len(p["receive"]):
                            st.write(f"📦 Turns {len(p['receive'])} into {len(p['give'])} — adds depth")
                        if give_avg_grade > recv_avg_grade:
                            st.write(f"⭐ Avg player quality up: {recv_avg_grade:.1f} → {give_avg_grade:.1f}")
                        give_pos = [g["position"] for g in p["give"]]
                        their_fits = [pos for pos in give_pos if pos in their_weak]
                        if their_fits:
                            st.write(f"🎯 Fills weak spot(s): **{', '.join(set(their_fits))}**")
                        if give_fpts > recv_fpts:
                            st.write(f"📊 More 2025 FPts coming in ({give_fpts:.0f} vs {recv_fpts:.0f})")

# ── Tab 4: Prospect Wire ──────────────────────────────────────────────────────
with tab4:
    st.subheader("🌱 Top Prospects — Waiver Wire")
    st.caption("Consensus 2026 rankings. Dynasty value blends pedigree, production, and level-for-age.")
    rostered = tuple(rosters_df["name"].dropna().unique().tolist())
    prospects_df = load_prospects(league_session, "hp3gi9z9mg6wf2p7", rostered)

    # ── Prospect dynasty value weight sliders ─────────────────────────────────
    with st.expander("⚖️ Dynasty Value Weights", expanded=False):
        sw1, sw2, sw3 = st.columns(3)
        with sw1:
            pw_pedigree = st.slider("Pedigree (Rank/Hype)", 0, 100, 55, step=5, key="pw_pedigree")
        with sw2:
            pw_production = st.slider("MiLB Production", 0, 100, 25, step=5, key="pw_production")
        with sw3:
            pw_level_age = st.slider("Level-for-Age", 0, 100, 20, step=5, key="pw_level_age")
        _pw_total = pw_pedigree + pw_production + pw_level_age or 100
        _nw_ped  = pw_pedigree   / _pw_total
        _nw_prod = pw_production / _pw_total
        _nw_lvl  = pw_level_age  / _pw_total
        st.caption(
            f"Normalized — Pedigree {_nw_ped:.0%} · Production {_nw_prod:.0%} · "
            f"Level/Age {_nw_lvl:.0%} · then × age multiplier"
        )

    # Recompute dynasty_value inline using slider weights (no cache invalidation)
    def _recompute_dynasty(df: pd.DataFrame, w_ped, w_prod, w_lvl) -> pd.DataFrame:
        df = df.copy()
        def _dv(row):
            pedigree  = float(row.get("pedigree_score") or 0)
            level_age = float(row.get("level_age_score") or 50)
            prod      = row.get("production_score")
            has_prod  = pd.notna(prod) and float(prod) > 0
            if has_prod:
                blended = w_ped * pedigree + w_prod * float(prod) + w_lvl * level_age
            else:
                # No production data — redistribute prod weight to pedigree
                total_no_prod = w_ped + w_lvl or 1
                blended = (w_ped / total_no_prod) * pedigree + (w_lvl / total_no_prod) * level_age
            return round(blended * float(row.get("age_multiplier") or 1.0), 1)
        df["dynasty_value"] = df.apply(_dv, axis=1)
        return df

    prospects_df = _recompute_dynasty(prospects_df, _nw_ped, _nw_prod, _nw_lvl)

    pc1, pc2, pc3 = st.columns([2, 1, 1])
    with pc1:
        pos_filter = st.selectbox("Filter by position",
            ["All"] + sorted(prospects_df["position"].dropna().unique().tolist()), key="prospect_pos")
    with pc2:
        sort_by = st.selectbox("Sort by", ["Consensus Rank", "Dynasty Value"], key="prospect_sort")
    with pc3:
        show_all = st.checkbox("Show rostered too", value=False)

    filtered = prospects_df.copy()
    if pos_filter != "All":
        filtered = filtered[filtered["position"] == pos_filter]
    if not show_all and filtered["available"].notna().any():
        filtered = filtered[filtered["available"] != False]  # noqa: E712

    if sort_by == "Dynasty Value":
        filtered = filtered.sort_values("dynasty_value", ascending=False)
    else:
        filtered = filtered.sort_values("consensus_rank", ascending=True)

    def colour_available(val):
        if val is True:  return "color: #2e8b2e; font-weight: bold"
        if val is False: return "color: #b02020"
        return ""

    raw_cols = ["consensus_rank","name","position","org","age","milb_level",
                "ops","hr","sb","era","k9","production_score","pedigree_score",
                "level_age_score","age_multiplier","dynasty_value","available"]
    raw_cols = [c for c in raw_cols if c in filtered.columns]

    # Build MiLB profile URLs using nameSlug from the API (most accurate)
    def _milb_url(row):
        mid = row.get("mlb_id")
        if pd.isna(mid) or not mid:
            return None
        try:
            from milb_stats import get_milb_slug
            slug = get_milb_slug(int(mid), str(row["name"]))
            return f"https://www.milb.com/player/{slug}"
        except Exception:
            return None

    display_p = _fix_age(_round_df(_rename(filtered[raw_cols], PROSPECT_COL_NAMES)))

    # Add MiLB link column
    if "mlb_id" in filtered.columns:
        display_p["MiLB Profile"] = [
            _milb_url(filtered.iloc[i]) if i < len(filtered) else None
            for i in range(len(display_p))
        ]

        # Rebuild from row to get name+id together cleanly
        display_p["MiLB Profile"] = [
            _milb_url(filtered.iloc[i]) if i < len(filtered) else None
            for i in range(len(display_p))
        ]

    col_cfg = _col_config(display_p)
    if "MiLB Profile" in display_p.columns:
        col_cfg["MiLB Profile"] = st.column_config.LinkColumn(
            "MiLB Profile", display_text="🔗 View", help="Open MiLB player page"
        )

    st.dataframe(display_p.style.applymap(colour_available, subset=["Available"]),
                 use_container_width=True, hide_index=True,
                 column_config=col_cfg)
    if filtered["available"].isna().all():
        st.warning("Could not verify availability — Fantrax may need a fresh cookie.")

# ── Tab 5: Savant Stats ───────────────────────────────────────────────────────
with tab5:
    st.subheader("🎯 Baseball Savant — Statcast Leaderboard")
    st.caption("Savant score = weighted percentile rank across key Statcast metrics.")
    sv1, sv2 = st.tabs(["🏏 Hitters", "⚾ Pitchers"])

    with sv1:
        if savant_hitters.empty:
            st.info("Could not load Savant hitter data.")
        else:
            show_ros_h = st.checkbox("Rostered players only", value=True, key="savant_h_roster")
            sh = savant_hitters.copy()
            if show_ros_h:
                sh = sh[sh["name"].str.lower().isin(set(rosters_df["name"].str.lower()))]
            display_sh = _round_df(_rename(sh, SAVANT_H_COL_NAMES))
            show_h_cols = [c for c in ["Player","PA","Savant Score","xwOBA","Barrel%","Sprint Spd","OAA"] if c in display_sh.columns]
            sel_h = st.dataframe(display_sh[show_h_cols], use_container_width=True, hide_index=True,
                                 on_select="rerun", selection_mode="single-row",
                                 column_config=_col_config(display_sh[show_h_cols]))
            if sel_h and sel_h.selection.rows:
                _sel_h_name = sh.iloc[sel_h.selection.rows[0]]["name"]
                if _sel_h_name != st.session_state.get("_last_savant_h_sel"):
                    st.session_state["_last_savant_h_sel"] = _sel_h_name
                    open_profile(_sel_h_name)
            elif not sel_h or not sel_h.selection.rows:
                st.session_state.pop("_last_savant_h_sel", None)

    with sv2:
        if savant_pitchers.empty:
            st.info("Could not load Savant pitcher data.")
        else:
            show_ros_p = st.checkbox("Rostered players only", value=True, key="savant_p_roster")
            sp = savant_pitchers.copy()
            if show_ros_p:
                sp = sp[sp["name"].str.lower().isin(set(rosters_df["name"].str.lower()))]
            display_sp = _round_df(_rename(sp, SAVANT_P_COL_NAMES))
            show_p_cols = [c for c in ["Player","PA","Savant Score","xwOBA against","xERA","ERA","ERA - xERA"] if c in display_sp.columns]
            sel_p = st.dataframe(display_sp[show_p_cols], use_container_width=True, hide_index=True,
                                 on_select="rerun", selection_mode="single-row",
                                 column_config=_col_config(display_sp[show_p_cols]))
            if sel_p and sel_p.selection.rows:
                _sel_p_name = sp.iloc[sel_p.selection.rows[0]]["name"]
                if _sel_p_name != st.session_state.get("_last_savant_p_sel"):
                    st.session_state["_last_savant_p_sel"] = _sel_p_name
                    open_profile(_sel_p_name)
            elif not sel_p or not sel_p.selection.rows:
                st.session_state.pop("_last_savant_p_sel", None)


# ── Tab 6: Trade Grader ───────────────────────────────────────────────────────
with tab6:
    st.subheader("⚖️ Past Trade Grader")
    st.caption(
        "Grades every trade in league history. Value = weighted FPts (2024/2025/proj) "
        "+ prospect dynasty bonus. Draft picks resolved to the player drafted with them."
    )

    if st.button("📥 Load Trade History", type="primary", key="load_trade_history"):
        st.session_state.pop("_graded_trades", None)
        st.session_state.pop("_trade_tree", None)
        st.session_state["_trade_history_loaded"] = False

    if not st.session_state.get("_trade_history_loaded", False):
        if st.session_state.get("_graded_trades") is None:
            with st.spinner("Fetching trade history from Fantrax..."):
                try:
                    from trade_grader import load_and_grade_all_trades
                    _prospect_df = load_prospects(
                        league_session, "hp3gi9z9mg6wf2p7",
                        tuple(rosters_df["name"].dropna().unique().tolist())
                    )
                    _graded, _tree = load_and_grade_all_trades(
                        league_session, history_df, graded_df, _prospect_df
                    )
                    st.session_state["_graded_trades"] = _graded
                    st.session_state["_trade_tree"]    = _tree
                    st.session_state["_trade_history_loaded"] = True
                    if not _graded:
                        st.warning("No trades returned — the Fantrax API may not support getTransactions for this league, or there are no trades yet.")
                except Exception as e:
                    st.error(f"Failed to load trade history: {e}")
                    import traceback; st.code(traceback.format_exc())
                    _graded, _tree = [], {}
        else:
            _graded = st.session_state["_graded_trades"]
            _tree   = st.session_state.get("_trade_tree", {})
            st.session_state["_trade_history_loaded"] = True
    else:
        _graded = st.session_state.get("_graded_trades", [])
        _tree   = st.session_state.get("_trade_tree", {})

    if st.session_state.get("_trade_history_loaded") and _graded:

        # ── Filters & sort ────────────────────────────────────────────────────
        all_trade_teams = sorted(set(
            tm for tr in _graded for tm in [tr["team_a"], tr["team_b"]] if tm
        ))
        all_years = sorted(set(tr["year"] for tr in _graded if tr["year"]), reverse=True)

        fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 1])
        with fc1:
            tg_team = st.selectbox("Team", ["All Teams"] + all_trade_teams, key="tg_team")
        with fc2:
            tg_year = st.selectbox("Year", ["All Years"] + all_years, key="tg_year")
        with fc3:
            tg_verdict = st.selectbox("Verdict", ["All", "🤝 Even", "✅ Won", "✅ Lost"], key="tg_verdict")
        with fc4:
            tg_sort = st.selectbox("Sort by", ["Newest", "Oldest", "Biggest Win", "Most Even"], key="tg_sort")

        filtered = _graded
        if tg_team != "All Teams":
            filtered = [t for t in filtered if tg_team in (t["team_a"], t["team_b"])]
        if tg_year != "All Years":
            filtered = [t for t in filtered if t["year"] == tg_year]
        if tg_verdict != "All":
            if tg_verdict == "🤝 Even":
                filtered = [t for t in filtered if "Even" in t["verdict"]]
            elif tg_verdict == "✅ Won" and tg_team != "All Teams":
                filtered = [t for t in filtered if tg_team in t["verdict"] and "✅" in t["verdict"]]
            elif tg_verdict == "✅ Lost" and tg_team != "All Teams":
                filtered = [t for t in filtered if "✅" in t["verdict"] and tg_team not in t["verdict"]]

        if tg_sort == "Oldest":
            filtered = sorted(filtered, key=lambda x: x["date"])
        elif tg_sort == "Biggest Win":
            filtered = sorted(filtered, key=lambda x: abs(x["diff"]), reverse=True)
        elif tg_sort == "Most Even":
            filtered = sorted(filtered, key=lambda x: abs(x["diff"]))
        # default: Newest (already sorted)

        st.caption(f"Showing {len(filtered)} of {len(_graded)} trades")

        # ── Grade colours ─────────────────────────────────────────────────────
        _GRADE_COLORS = {
            "A+":"#1a7a1a","A":"#2e8b2e","A-":"#3d9e3d",
            "B+":"#5a8a00","B":"#7a9e00","B-":"#9ab000",
            "C+":"#c8a000","C":"#d4880a","C-":"#d46a0a",
            "D+":"#c84040","D":"#b02020","F":"#800000",
        }

        def _render_player_entry(p: dict):
            """Render one player row inside a trade side."""
            fpts_line = (
                f"2025: {p['fpts_2025']:.0f} · "
                f"2024: {p['fpts_2024']:.0f} · "
                f"Proj: {p['fpts_proj']:.0f}"
            )
            if p["is_pick"]:
                if p["resolved_player"]:
                    badge = f"🎟️ Pick → **{p['resolved_player']}**"
                else:
                    badge = "🎟️ Pick (unresolved)"
                st.markdown(
                    f"{badge} · Dynasty est: {p['prospect_value']:.0f}  \n"
                    f"<span style='color:#888;font-size:11px'>{fpts_line}</span>",
                    unsafe_allow_html=True,
                )
            elif p["is_prospect"]:
                st.markdown(
                    f"**{p['name']}** ({p['position']}) 🌱  \n"
                    f"<span style='color:#888;font-size:11px'>"
                    f"Dynasty Value: {p['prospect_value']:.0f} · {fpts_line}</span>",
                    unsafe_allow_html=True,
                )
            else:
                gc = _GRADE_COLORS.get(p["grade"], "#888")
                st.markdown(
                    f"**{p['name']}** ({p['position']}) "
                    f"<span style='color:{gc}'>{p['grade']}</span>  \n"
                    f"<span style='color:#888;font-size:11px'>{fpts_line}</span>",
                    unsafe_allow_html=True,
                )
            # Trade tree — show if this player was traded again
            tree_entries = _tree.get(
                (p.get("score_name") or "").lower(),
                _tree.get((p.get("name") or "").lower(), [])
            )
            if len(tree_entries) > 1:
                display_name = p.get("score_name") or p.get("name") or "Player"
                with st.expander(f"🔀 Trade tree for {display_name} ({len(tree_entries)} trades)"):
                    for idx, te in enumerate(tree_entries):
                        a_names = " + ".join(
                            (e.get("resolved_player") or e["name"]) for e in te.get("a_gets", [])
                        )
                        b_names = " + ".join(
                            (e.get("resolved_player") or e["name"]) for e in te.get("b_gets", [])
                        )
                        st.markdown(
                            f"**{te['date']}** — {te['team_a']} gets {a_names} "
                            f"← → {te['team_b']} gets {b_names}"
                        )

        for trade in filtered:
            team_a  = trade["team_a"]
            team_b  = trade["team_b"]
            verdict = trade["verdict"]
            diff    = trade["diff"]
            diff_str = f"{'+' if diff >= 0 else ''}{diff:.0f}"
            a_names = " + ".join(
                (f"[Pick→{e['resolved_player']}]" if e.get("resolved_player") else
                 "[Pick]" if e["is_pick"] else e["name"])
                for e in trade["a_gets"]
            )
            b_names = " + ".join(
                (f"[Pick→{e['resolved_player']}]" if e.get("resolved_player") else
                 "[Pick]" if e["is_pick"] else e["name"])
                for e in trade["b_gets"]
            )

            v_color = "#888" if "Even" in verdict else (
                "#2e8b2e" if team_a in verdict else "#c84040"
            )
            label = (
                f"{verdict}  |  {trade['date']}  |  "
                f"{team_a}: {a_names}  ←→  {team_b}: {b_names}  |  Δ {diff_str}"
            )

            with st.expander(label):
                st.markdown(
                    f"<p style='text-align:center;font-size:1.1rem'>"
                    f"<span style='color:{v_color};font-weight:bold'>{verdict}</span>"
                    f" &nbsp;·&nbsp; Value diff: <b>{diff_str}</b>"
                    f" &nbsp;·&nbsp; {trade['date']}</p>",
                    unsafe_allow_html=True,
                )

                gc1, gc2 = st.columns(2)
                with gc1:
                    st.markdown(f"**📥 {team_a} received**")
                    for p in trade["a_players"]:
                        _render_player_entry(p)
                    st.metric("Side Value", f"{trade['a_total']:.0f}")
                with gc2:
                    st.markdown(f"**📥 {team_b} received**")
                    for p in trade["b_players"]:
                        _render_player_entry(p)
                    st.metric("Side Value", f"{trade['b_total']:.0f}")

                # Value comparison bar
                _bar_df = pd.DataFrame({
                    "Team":  [team_a, team_b],
                    "Value": [trade["a_total"], trade["b_total"]],
                }).set_index("Team")
                st.bar_chart(_bar_df)

    elif st.session_state.get("_trade_history_loaded"):
        st.info("No trades found in league history.")
    else:
        st.info("👆 Hit **Load Trade History** to grade all past trades.")


# ── Single dialog render (must be called once per script run) ─────────────────
_profile_name = st.session_state.pop("_profile_player", None)
_profile_pending = st.session_state.pop("_profile_pending", False)
if _profile_name and _profile_pending:
    _render_player_profile(
        _profile_name, graded_df, history_df,
        savant_hitters, savant_pitchers, mlb_id_map,
        league_session,
        savant_pct_hitters, savant_pct_pitchers,
    )
