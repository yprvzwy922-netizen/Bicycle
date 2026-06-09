"""
Shared data-fetching helpers for the public app.
All functions are @st.cache_data decorated.
No DB dependency — pure yfinance + session_state watchlist.
"""
import datetime
import sys, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from scipy.stats import norm

# ── Default watchlist ─────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    {"ticker": "IREN",  "company": "IREN Ltd",               "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "CIFR",  "company": "Cipher Digital",          "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "NBIS",  "company": "Nebius Group",            "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CRWV",  "company": "CoreWeave",               "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CEG",   "company": "Constellation Energy",    "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "DGXX",  "company": "Digi Power X",            "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "VRT",   "company": "Vertiv",                  "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "GEV",   "company": "GE Vernova",              "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVDA",  "company": "NVIDIA",                  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MU",    "company": "Micron",                  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMD",   "company": "Advanced Micro Devices",  "sector": "Semiconductors",       "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "GOOG",  "company": "Alphabet",                "sector": "Technology",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "BB",    "company": "BlackBerry",              "sector": "Technology",           "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "UBER",  "company": "Uber Technologies",       "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "LLY",   "company": "Eli Lilly",               "sector": "Healthcare",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVO",   "company": "Novo Nordisk",            "sector": "Healthcare",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMGN",  "company": "Amgen",                   "sector": "Healthcare",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "HIMS",  "company": "Hims & Hers",             "sector": "Healthcare",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "VKTX",  "company": "Viking Therapeutics",     "sector": "Healthcare",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "IBRX",  "company": "ImmunityBio",             "sector": "Healthcare",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
]

SECTORS = sorted(set(w["sector"] for w in DEFAULT_WATCHLIST))
TICKERS = [w["ticker"] for w in DEFAULT_WATCHLIST]

def get_watchlist():
    """Returns session watchlist (starts from defaults, editable during session)."""
    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = {w["ticker"]: w for w in DEFAULT_WATCHLIST}
    return list(st.session_state["watchlist"].values())

def add_to_watchlist(ticker, company="", sector="Technology", bucket="Growth", conviction=3, delta_band="Income"):
    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = {w["ticker"]: w for w in DEFAULT_WATCHLIST}
    st.session_state["watchlist"][ticker.upper()] = {
        "ticker": ticker.upper(), "company": company, "sector": sector,
        "bucket": bucket, "conviction": conviction, "delta_band": delta_band
    }

def remove_from_watchlist(ticker):
    if "watchlist" in st.session_state:
        st.session_state["watchlist"].pop(ticker.upper(), None)

# ── Math ──────────────────────────────────────────────────────────────────────
def _bs_delta(spot, strike, iv, dte, rf, kind):
    """Vectorized Black-Scholes delta. `strike`/`iv` may be scalars or arrays.
    Returns a float for scalar input, a numpy array otherwise."""
    strike = np.asarray(strike, dtype=float)
    iv     = np.asarray(iv, dtype=float)
    scalar = strike.ndim == 0 and iv.ndim == 0
    T = dte / 365.0
    with np.errstate(divide="ignore", invalid="ignore"):
        d1  = (np.log(spot/strike) + (rf + 0.5*iv**2)*T) / (iv*np.sqrt(T))
        out = np.abs(norm.cdf(d1) - 1) if kind == "put" else norm.cdf(d1)
    invalid = (dte <= 0) | (iv <= 0) | (spot <= 0) | (strike <= 0)
    out = np.where(invalid, np.nan, out)
    return float(out) if scalar else out

def bs_put_delta(spot, strike, iv, dte, rf=0.053):
    return _bs_delta(spot, strike, iv, dte, rf, "put")

def bs_call_delta(spot, strike, iv, dte, rf=0.053):
    return _bs_delta(spot, strike, iv, dte, rf, "call")

def moneyness(spot, strike, is_put=True):
    b = 0.01 * spot
    if is_put:
        if strike < spot - b: return "OTM"
        if strike > spot + b: return "ITM"
    else:
        if strike > spot + b: return "OTM"
        if strike < spot - b: return "ITM"
    return "ATM"

def ann_yield(prem, strike, dte):
    return (prem/strike)*(365/dte) if strike and dte else float("nan")

def ann_roll(net_credit, strike_new, added_dte):
    return (net_credit/strike_new)*(365/added_dte) if strike_new and added_dte else float("nan")

# ── Realized vol percentile (IV Rank proxy) ───────────────────────────────────
def rv_percentile(hist):
    """Use 1-year realized vol percentile as IV Rank proxy."""
    if hist.empty or len(hist) < 60: return 0.5
    ret = hist["Close"].pct_change().dropna()
    rv = ret.rolling(21).std() * np.sqrt(252)
    rv = rv.dropna()
    if len(rv) < 10: return 0.5
    lo, hi = rv.min(), rv.max()
    if hi == lo: return 0.5
    return float(np.clip((rv.iloc[-1] - lo) / (hi - lo), 0, 1))

# ── Data fetching ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_spot(tkr):
    try:
        info = yf.Ticker(tkr).fast_info
        p = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if p is None:
            h = yf.Ticker(tkr).history(period="2d")
            p = float(h["Close"].iloc[-1]) if not h.empty else float("nan")
        return float(p)
    except Exception:
        return float("nan")

@st.cache_data(ttl=600, show_spinner=False)
def fetch_hist(tkr):
    try:
        return yf.Ticker(tkr).history(period="1y")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def _as_date(d):
    """Coerce datetime.date / datetime.datetime / pandas.Timestamp -> date."""
    if d is None:
        return None
    if hasattr(d, "date") and not isinstance(d, datetime.date):
        return d.date()                 # datetime / Timestamp
    if isinstance(d, datetime.date):
        return d                        # already a date
    try:
        return pd.Timestamp(d).date()   # strings, numpy datetimes, etc.
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings(tkr):
    """Days until the next earnings date (>=0), or None if unavailable."""
    today = datetime.date.today()
    candidates = []
    try:
        t = yf.Ticker(tkr)

        # 1) calendar (dict in modern yfinance, sometimes a DataFrame)
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                for d in cal.get("Earnings Date", []) or []:
                    dd = _as_date(d)
                    if dd: candidates.append(dd)
            elif cal is not None and hasattr(cal, "columns"):
                for col in cal.columns:
                    dd = _as_date(col)
                    if dd: candidates.append(dd)
        except Exception:
            pass

        # 2) earnings_dates table (covers past + future)
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                for ts in ed.index:
                    dd = _as_date(ts)
                    if dd: candidates.append(dd)
        except Exception:
            pass

        # 3) get_earnings_dates fallback
        if not candidates:
            try:
                ed2 = t.get_earnings_dates(limit=8)
                if ed2 is not None and not ed2.empty:
                    for ts in ed2.index:
                        dd = _as_date(ts)
                        if dd: candidates.append(dd)
            except Exception:
                pass
    except Exception:
        return None

    # Nearest future date (today counts as 0)
    future = sorted(d for d in candidates if d >= today)
    if future:
        return (future[0] - today).days
    return None

@st.cache_data(ttl=300, show_spinner=False)
def fetch_expirations(tkr):
    try:
        return list(yf.Ticker(tkr).options)
    except Exception:
        return []

def is_third_friday(d: datetime.date) -> bool:
    """True if date is the 3rd Friday of its month (standard monthly option expiry)."""
    return d.weekday() == 4 and 15 <= d.day <= 21

@st.cache_data(ttl=300, show_spinner=False)
def fetch_chain(tkr, target_dte, option_type="put", monthly_only=False):
    try:
        t = yf.Ticker(tkr)
        exps = list(t.options)
        if not exps: return None, None, None
        today = datetime.date.today()

        # For longer tenors, restrict to standard monthly contracts (3rd Friday),
        # which carry the deepest liquidity. Fall back to all if none qualify.
        candidates = exps
        if monthly_only:
            monthlies = [e for e in exps
                         if is_third_friday(datetime.datetime.strptime(e, "%Y-%m-%d").date())]
            if monthlies:
                candidates = monthlies

        best = min(candidates, key=lambda e: abs(
            (datetime.datetime.strptime(e, "%Y-%m-%d").date() - today).days - target_dte))
        dte = (datetime.datetime.strptime(best, "%Y-%m-%d").date() - today).days
        raw = t.option_chain(best)
        chain = (raw.puts if option_type == "put" else raw.calls).copy()
        chain["mid"] = (chain["bid"] + chain["ask"]) / 2
        chain["spread_pct"] = (chain["ask"] - chain["bid"]) / chain["mid"].replace(0, np.nan)
        chain["dte"] = dte
        return chain, best, dte
    except Exception:
        return None, None, None

def prefetch(tickers, dtes=(35,), option_type="put"):
    """Warm the per-ticker caches concurrently so the screener's main loop
    hits warm caches instead of blocking on sequential network I/O.
    st.cache_data is process-wide and thread-safe, so threads populate the
    same cache the main thread reads."""
    def warm(tkr):
        try:
            fetch_spot(tkr)
            fetch_hist(tkr)
            fetch_earnings(tkr)
            for d in dtes:
                fetch_chain(tkr, d, option_type)
        except Exception:
            pass
    if not tickers:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as ex:
        list(ex.map(warm, tickers))

def trend_label_score(hist):
    if hist.empty or len(hist) < 20: return "N/A", 2.5
    c = hist["Close"]
    e50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    e200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
    p = c.iloc[-1]
    if p > e50 > e200: return "UP", 5.0
    if p > e200:       return "UP (WEAK)", 3.5
    if p < e50 < e200: return "DOWN", 1.0
    return "NEUTRAL", 2.5

def score_strikes(sub, target_delta, weights):
    """Add a 0-100 'score' column balancing yield, cushion, delta-fit, liquidity.
    Same logic the Option Finder uses. `sub` needs columns:
    ann_yield, cushion_pct, delta, spread_pct."""
    def _minmax(s):
        s = s.astype(float)
        rng = s.max() - s.min()
        if rng == 0 or np.isnan(rng):
            return pd.Series(1.0, index=s.index)
        return (s - s.min()) / rng
    sc_yield   = _minmax(sub["ann_yield"])
    sc_cushion = _minmax(sub["cushion_pct"])
    sc_delta   = 1 - _minmax((sub["delta"] - target_delta).abs())
    sc_liq     = 1 - _minmax(sub["spread_pct"].fillna(sub["spread_pct"].max()))
    return (weights["yield"]   * sc_yield   +
            weights["cushion"] * sc_cushion +
            weights["delta"]   * sc_delta   +
            weights["liq"]     * sc_liq) * 100

def best_put(tkr, delta_band, target_dte):
    # Band bounds + scoring weights match the Option Finder
    if delta_band == "Income":
        lo, hi, target = 0.15, 0.30, 0.225
        weights = {"yield":0.25, "cushion":0.35, "delta":0.25, "liq":0.15}
    else:  # Wheel
        lo, hi, target = 0.30, 0.45, 0.375
        weights = {"yield":0.40, "cushion":0.25, "delta":0.20, "liq":0.15}

    spot = fetch_spot(tkr)
    chain, expiry, dte = fetch_chain(tkr, target_dte, "put")
    if chain is None or chain.empty: return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    chain["delta"] = bs_put_delta(spot, chain["strike"].values,
                                  chain["impliedVolatility"].values, dte)

    # Restrict to the band; fall back to a wider window only if empty
    sub = chain[(chain["delta"] >= lo) & (chain["delta"] <= hi)].copy()
    if sub.empty:
        sub = chain[(chain["delta"] >= lo*0.5) & (chain["delta"] <= hi*1.8)].copy()
    if sub.empty:
        sub = chain.copy()

    # Enrich for scoring (vectorized)
    sub["mid"]         = sub["mid"].fillna(sub["bid"])
    sub["ann_yield"]   = (sub["mid"] / sub["strike"]) * (365.0 / dte)
    sub["cushion_pct"] = (spot - sub["strike"]) / spot if spot else np.nan
    if "spread_pct" not in sub.columns:
        sub["spread_pct"] = (sub["ask"] - sub["bid"]) / sub["mid"].replace(0, np.nan)

    # Highest-scoring strike in the band
    sub["score"] = score_strikes(sub, target, weights)
    row = sub.loc[sub["score"].idxmax()]

    prem   = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
    strike = float(row["strike"])
    sp = float((row["ask"]-row["bid"])/row["mid"]) if row["mid"] > 0 else float("nan")
    return {"expiry": expiry, "dte": dte, "strike": strike,
            "delta": round(float(row["delta"]), 3),
            "iv": round(float(row["impliedVolatility"]), 4),
            "premium": round(prem, 2),
            "ann_yield": round(ann_yield(prem, strike, dte), 4),
            "cushion": round((spot-strike)/spot if spot else float("nan"), 4),
            "breakeven": round(strike - prem, 2),
            "oi": int(row.get("openInterest", 0) or 0),
            "spread_pct": round(sp, 3),
            "score": round(float(row["score"]), 1)}

def best_call(tkr, target_delta, target_dte):
    """Best covered call — OTM call closest to target_delta."""
    spot = fetch_spot(tkr)
    chain, expiry, dte = fetch_chain(tkr, target_dte, "call")
    if chain is None or chain.empty: return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    # Only OTM calls (strike > spot)
    otm = chain[chain["strike"] > spot * 0.99]
    if otm.empty: otm = chain
    otm = otm.copy()
    otm["delta"] = bs_call_delta(spot, otm["strike"].values,
                                 otm["impliedVolatility"].values, dte)
    otm["dist"] = (otm["delta"] - target_delta).abs()
    row = otm.loc[otm["dist"].idxmin()]
    prem = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
    strike = float(row["strike"])
    sp = float((row["ask"]-row["bid"])/row["mid"]) if row["mid"] > 0 else float("nan")
    return {"expiry": expiry, "dte": dte, "strike": strike,
            "delta": round(float(row["delta"]), 3),
            "iv": round(float(row["impliedVolatility"]), 4),
            "premium": round(prem, 2),
            "ann_yield": round(ann_yield(prem, spot, dte), 4),  # yield on stock value
            "upside_cap": round((strike - spot)/spot, 4),
            "breakeven_up": round(spot + prem, 2),
            "oi": int(row.get("openInterest", 0) or 0),
            "spread_pct": round(sp, 3)}

def best_bear_call_spread(tkr, short_delta, spread_width_pct, target_dte):
    """
    Bear call spread: sell short_delta call, buy call at strike + spread_width.
    spread_width_pct: e.g. 0.05 = 5% of spot above short strike.
    """
    spot = fetch_spot(tkr)
    chain, expiry, dte = fetch_chain(tkr, target_dte, "call")
    if chain is None or chain.empty: return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    otm = chain[chain["strike"] > spot * 0.99].copy()
    if otm.empty: return {}
    otm["delta"] = bs_call_delta(spot, otm["strike"].values,
                                 otm["impliedVolatility"].values, dte)
    otm["dist"] = (otm["delta"] - short_delta).abs()
    short_row = otm.loc[otm["dist"].idxmin()]
    short_strike = float(short_row["strike"])
    short_prem = float(short_row["mid"]) if not np.isnan(short_row["mid"]) else float(short_row["bid"])

    # Long leg: next strike at least spread_width above short
    long_target = short_strike * (1 + spread_width_pct)
    long_candidates = chain[chain["strike"] >= long_target]
    if long_candidates.empty: return {}
    long_row = long_candidates.iloc[0]
    long_strike = float(long_row["strike"])
    long_prem = float(long_row["mid"]) if not np.isnan(long_row["mid"]) else float(long_row["bid"])

    net_credit = round(short_prem - long_prem, 2)
    spread_width = round(long_strike - short_strike, 2)
    max_loss = round(spread_width - net_credit, 2)
    roc = round(net_credit / max_loss, 4) if max_loss > 0 else float("nan")

    return {"expiry": expiry, "dte": dte,
            "short_strike": short_strike, "long_strike": long_strike,
            "short_delta": round(float(short_row["delta"]), 3),
            "short_iv": round(float(short_row["impliedVolatility"]), 4),
            "net_credit": net_credit,
            "spread_width": spread_width,
            "max_loss": max_loss,
            "breakeven": round(short_strike + net_credit, 2),
            "roc": roc,
            "ann_roc": round(roc * 365/dte, 4) if dte > 0 and not np.isnan(roc) else float("nan"),
            "oi": int(short_row.get("openInterest", 0) or 0)}

@st.cache_data(ttl=60, show_spinner=False)  # 1-min cache — live option prices
def fetch_option_live(tkr: str, strike: float, expiry: str, option_type: str = "put"):
    """
    Returns (current_mid, current_iv) for a specific option contract.
    Used by Portfolio to mark-to-market open positions.
    """
    try:
        raw = yf.Ticker(tkr).option_chain(expiry)
        chain = raw.puts if option_type == "put" else raw.calls
        chain = chain.copy()
        chain["dist"] = (chain["strike"] - strike).abs()
        row = chain.loc[chain["dist"].idxmin()]
        mid = float((row["bid"] + row["ask"]) / 2)
        iv  = float(row["impliedVolatility"])
        return mid, iv
    except Exception:
        return float("nan"), float("nan")


def score_put(ivr, ann_y, oi, sp, earn, dte_t, tech_s, conv):
    ivr_s = 1 + ivr * 4
    yld_s = (5 if ann_y >= 0.40 else 4 if ann_y >= 0.25 else 3 if ann_y >= 0.15 else 2 if ann_y >= 0.08 else 1) if not np.isnan(ann_y) else 1
    liq_s = max(1, min(5, 3 + (1 if oi > 5000 else -1 if oi < 300 else 0) +
                       (1 if not np.isnan(sp) and sp < 0.03 else -1 if not np.isnan(sp) and sp > 0.10 else 0)))
    earn_s = 5 if earn is None or earn > dte_t+5 else 4 if earn > dte_t else 2 if earn > 7 else 1
    sc = 0.30*ivr_s + 0.25*yld_s + 0.15*liq_s + 0.10*earn_s + 0.10*tech_s + 0.10*float(conv)
    vd = "TRADE" if sc >= 3.8 else ("WATCH" if sc >= 3.0 else "PASS")
    return round(sc, 2), vd
