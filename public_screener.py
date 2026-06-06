"""
Public Put-Selling Screener
Deployed to Streamlit Cloud — screener only, no positions or personal data.
Password-protected via st.secrets (set SCREENER_PASSWORD in Streamlit Cloud secrets).
"""
import os
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Put-Selling Screener",
    page_icon="📊",
    layout="wide",
)

# ── Password gate ─────────────────────────────────────────────────────────────
PASSWORD = st.secrets.get("SCREENER_PASSWORD", "") if hasattr(st, "secrets") else ""

if PASSWORD:
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("📊 Put-Selling Screener")
        pwd = st.text_input("Enter password", type="password")
        if st.button("Login"):
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.stop()

# ── Watchlist ─────────────────────────────────────────────────────────────────
WATCHLIST = [
    {"ticker": "IREN",  "company": "IREN Ltd",               "sector": "AI data center",         "bucket": "Growth",      "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "CIFR",  "company": "Cipher Digital",          "sector": "Crypto / HPC",           "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "NBIS",  "company": "Nebius Group",            "sector": "AI data center",         "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CRWV",  "company": "CoreWeave",               "sector": "AI data center",         "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CEG",   "company": "Constellation Energy",    "sector": "Power / nuclear",        "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "DGXX",  "company": "Digi Power X",            "sector": "Energy / AI data center","bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "VRT",   "company": "Vertiv",                  "sector": "Power / DC equip",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "GEV",   "company": "GE Vernova",              "sector": "Power / grid equip",     "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVDA",  "company": "NVIDIA",                  "sector": "AI compute / semis",     "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MU",    "company": "Micron",                  "sector": "AI compute / semis",     "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMD",   "company": "Advanced Micro Devices",  "sector": "AI compute / semis",     "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "GOOG",  "company": "Alphabet",                "sector": "Comm services",          "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "BB",    "company": "BlackBerry",              "sector": "Software / security",    "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "LLY",   "company": "Eli Lilly",               "sector": "Healthcare / peptides",  "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVO",   "company": "Novo Nordisk",            "sector": "Healthcare / peptides",  "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMGN",  "company": "Amgen",                   "sector": "Healthcare / pharma",    "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "HIMS",  "company": "Hims & Hers",             "sector": "Healthcare / telehealth","bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "VKTX",  "company": "Viking Therapeutics",     "sector": "Healthcare / peptides",  "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "IBRX",  "company": "ImmunityBio",             "sector": "Healthcare / biotech",   "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
]

# ── Inline math (no local imports needed for cloud) ───────────────────────────
from scipy.stats import norm

def bs_put_delta(spot, strike, iv, dte, rf=0.053):
    if dte <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return float("nan")
    T = dte / 365.0
    d1 = (np.log(spot / strike) + (rf + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    return abs(norm.cdf(d1) - 1)

def annualized_yield(premium, strike, dte):
    if strike == 0 or dte == 0: return float("nan")
    return (premium / strike) * (365 / dte)

def downside_cushion(spot, strike):
    if spot == 0: return float("nan")
    return (spot - strike) / spot

def moneyness_label(spot, strike):
    band = 0.01 * spot
    if strike < spot - band: return "OTM"
    if strike > spot + band: return "ITM"
    return "ATM"

def screening_score(ivr, yld, liq, earn, tech, conv):
    return 0.30*ivr + 0.25*yld + 0.15*liq + 0.10*earn + 0.10*tech + 0.10*conv

def verdict(score):
    if score >= 4: return "TRADE"
    if score >= 3: return "Watch"
    return "Pass"

# ── Data fetching (cached) ─────────────────────────────────────────────────────
import yfinance as yf
import datetime

@st.cache_data(ttl=300, show_spinner=False)
def fetch_spot(ticker):
    t = yf.Ticker(ticker)
    info = t.fast_info
    price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
    if price is None:
        h = t.history(period="2d")
        price = float(h["Close"].iloc[-1]) if not h.empty else float("nan")
    return float(price)

@st.cache_data(ttl=600, show_spinner=False)
def fetch_history(ticker):
    return yf.Ticker(ticker).history(period="1y")

@st.cache_data(ttl=300, show_spinner=False)
def fetch_chain(ticker, target_dte=35):
    t = yf.Ticker(ticker)
    exps = list(t.options)
    if not exps:
        return None, None, None
    today = datetime.date.today()
    best, best_diff = exps[0], 9999
    for e in exps:
        d = (datetime.datetime.strptime(e, "%Y-%m-%d").date() - today).days
        if abs(d - target_dte) < best_diff:
            best, best_diff = e, abs(d - target_dte)
    chain = t.option_chain(best).puts.copy()
    dte = (datetime.datetime.strptime(best, "%Y-%m-%d").date() - today).days
    chain["mid"] = (chain["bid"] + chain["ask"]) / 2
    chain["dte"] = dte
    return chain, best, dte

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings(ticker):
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            future = ed[ed.index.tz_localize(None) > pd.Timestamp.now()] if ed.index.tz is not None else ed[ed.index > pd.Timestamp.now()]
            if not future.empty:
                return (future.index[0].date() - datetime.date.today()).days
    except Exception:
        pass
    return None

def best_put(ticker, delta_band, target_dte=35):
    lo, hi = (0.15, 0.30) if delta_band == "Income" else (0.30, 0.45)
    target = (lo + hi) / 2
    spot = fetch_spot(ticker)
    chain, expiry, dte = fetch_chain(ticker, target_dte)
    if chain is None or chain.empty:
        return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    chain["delta"] = chain.apply(
        lambda r: bs_put_delta(spot, r["strike"], r["impliedVolatility"], dte), axis=1)
    in_range = chain[(chain["delta"] >= lo * 0.6) & (chain["delta"] <= hi * 1.6)]
    if in_range.empty:
        in_range = chain
    in_range = in_range.copy()
    in_range["dist"] = (in_range["delta"] - target).abs()
    row = in_range.loc[in_range["dist"].idxmin()]
    prem   = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
    strike = float(row["strike"])
    return {
        "expiry": expiry, "dte": dte, "strike": strike,
        "delta": round(float(row["delta"]), 3),
        "iv": round(float(row["impliedVolatility"]), 4),
        "premium": round(prem, 2),
        "ann_yield": round(annualized_yield(prem, strike, dte), 4),
        "cushion": round(downside_cushion(spot, strike), 4),
        "breakeven": round(strike - prem, 2),
        "oi": int(row.get("openInterest", 0) or 0),
        "spread_pct": round(float((row["ask"]-row["bid"])/row["mid"]) if row["mid"] > 0 else float("nan"), 3),
    }

def trend_and_score(ticker):
    hist = fetch_history(ticker)
    if hist.empty or len(hist) < 20:
        return "Unknown", 2.5
    close = hist["Close"]
    ema50  = close.ewm(span=50,  adjust=False).mean().iloc[-1]
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
    price  = close.iloc[-1]
    if price > ema50 > ema200: return "↑ Up", 5.0
    if price > ema200:         return "↑ Weak", 3.5
    return "↓ Down", 1.5

def build_row(w):
    tkr = w["ticker"]
    spot = fetch_spot(tkr)
    delta_band = w["delta_band"]
    conv = w["conviction"]
    put1m = best_put(tkr, delta_band, 35)
    put3m = best_put(tkr, delta_band, 90)
    trend, tech_score = trend_and_score(tkr)
    earn = fetch_earnings(tkr)

    # sub-scores
    ann_y = put1m.get("ann_yield", float("nan"))
    oi    = put1m.get("oi", 0)
    sp    = put1m.get("spread_pct", float("nan"))
    dte_t = put1m.get("dte", 35) or 35

    ivr_s  = 2.5   # no history yet on cloud
    yld_s  = 5 if not np.isnan(ann_y) and ann_y >= 0.30 else (4 if ann_y >= 0.20 else (3 if ann_y >= 0.12 else (2 if ann_y >= 0.06 else 1))) if not np.isnan(ann_y) else 1
    liq_s  = max(1, min(5, 3 + (1 if oi > 5000 else -1 if oi < 500 else 0) + (1 if not np.isnan(sp) and sp < 0.03 else -1 if not np.isnan(sp) and sp > 0.10 else 0)))
    earn_s = (5 if earn is None or earn > dte_t + 5 else 4 if earn > dte_t else 2 if earn > 7 else 1)

    score = screening_score(ivr_s, yld_s, liq_s, earn_s, tech_score, float(conv))

    illiquid = (not np.isnan(sp) and sp > 0.10) if not np.isnan(put1m.get("spread_pct", float("nan"))) else False

    return {
        "Ticker":          tkr,
        "Company":         w["company"],
        "Sector":          w["sector"],
        "Bucket":          w["bucket"],
        "Price":           round(spot, 2),
        "Trend":           trend,
        "Days to Earn.":   earn,
        "Band":            delta_band,
        "1M Strike":       put1m.get("strike"),
        "1M Delta":        put1m.get("delta"),
        "1M IV":           put1m.get("iv"),
        "1M Ann Yield":    put1m.get("ann_yield"),
        "1M Cushion":      put1m.get("cushion"),
        "1M Premium":      put1m.get("premium"),
        "1M Expiry":       put1m.get("expiry"),
        "3M Strike":       put3m.get("strike"),
        "3M Delta":        put3m.get("delta"),
        "3M Ann Yield":    put3m.get("ann_yield"),
        "3M Cushion":      put3m.get("cushion"),
        "3M Premium":      put3m.get("premium"),
        "Score":           round(score, 2),
        "Verdict":         verdict(score),
        "Illiquid ⚠️":    "⚠️" if illiquid else "",
    }

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("📊 Put-Selling Screener")
st.caption("Live data via yfinance · Refreshes every 5 min · Decision support only — reconcile with your broker before trading.")

# Filters
with st.sidebar:
    st.header("Filters")
    f_trend    = st.checkbox("Trend Up only", False)
    f_earn     = st.checkbox("No earnings inside DTE window", True)
    f_min_yld  = st.slider("Min 1M ann. yield", 0.0, 0.50, 0.06, 0.01, format="%.0f%%")
    f_max_delt = st.slider("Max 1M delta", 0.10, 0.60, 0.45, 0.01)
    f_buckets  = st.multiselect("Buckets", ["Core","Growth","Speculative"], default=[])
    f_sectors  = st.multiselect("Sectors",
        sorted(set(w["sector"] for w in WATCHLIST)), default=[])
    f_verdict  = st.selectbox("Min verdict", ["Pass","Watch","TRADE"], index=0)
    st.markdown("---")
    st.caption("Strike = BS delta closest to band centre.\nIV Rank requires daily snapshots — shows after 5+ days.")

if st.button("🔄  Refresh data", type="primary"):
    st.cache_data.clear()

# Load
rows, errors = [], []
prog = st.progress(0, text="Loading…")
for i, w in enumerate(WATCHLIST):
    try:
        rows.append(build_row(w))
    except Exception as e:
        errors.append(f"{w['ticker']}: {e}")
    prog.progress((i+1)/len(WATCHLIST), text=f"Loading {w['ticker']}…")
prog.empty()

if errors:
    with st.expander(f"⚠️  {len(errors)} ticker(s) had errors"):
        for e in errors: st.text(e)

df = pd.DataFrame(rows)

# Apply filters
v_order = {"Pass":0,"Watch":1,"TRADE":2}
if f_trend:
    df = df[df["Trend"].str.contains("Up", na=False)]
if f_earn and "Days to Earn." in df.columns:
    df = df[df["Days to Earn."].isna() | (df["Days to Earn."] > df["1M Expiry"].apply(
        lambda e: (datetime.datetime.strptime(e, "%Y-%m-%d").date() - datetime.date.today()).days
        if isinstance(e, str) else 35))]
if f_min_yld > 0:
    df = df[df["1M Ann Yield"].fillna(0) >= f_min_yld]
if f_max_delt < 0.60:
    df = df[df["1M Delta"].fillna(1.0) <= f_max_delt]
if f_buckets:
    df = df[df["Bucket"].isin(f_buckets)]
if f_sectors:
    df = df[df["Sector"].isin(f_sectors)]
if f_verdict != "Pass":
    df = df[df["Verdict"].map(v_order).fillna(0) >= v_order[f_verdict]]

# Display
def fmt(v, style):
    if v is None or (isinstance(v, float) and np.isnan(v)): return "—"
    try:
        if style == "$":   return f"${v:.2f}"
        if style == "%":   return f"{v:.1%}"
        if style == "d":   return f"{v:.3f}"
        if style == "i":   return str(int(v))
    except: return "—"
    return str(v)

SHOW = ["Ticker","Company","Sector","Bucket","Price","Trend","Days to Earn.",
        "Band","1M Strike","1M Delta","1M IV","1M Ann Yield","1M Cushion","1M Premium","1M Expiry",
        "3M Strike","3M Delta","3M Ann Yield","3M Cushion","3M Premium",
        "Score","Verdict","Illiquid ⚠️"]

disp = df[[c for c in SHOW if c in df.columns]].copy()

def style_verdict(v):
    return {"TRADE":"background-color:#1a6b1a;color:white",
            "Watch":"background-color:#7a6000;color:white",
            "Pass": "background-color:#4a1a1a;color:white"}.get(v,"")

def style_trend(v):
    if "Up" in str(v):   return "color:#4caf50;font-weight:bold"
    if "Down" in str(v): return "color:#f44336"
    return ""

def style_earn(v):
    try: return "color:red;font-weight:bold" if int(v) < 35 else ""
    except: return ""

styled = (
    disp.style
    .map(style_verdict, subset=["Verdict"])
    .map(style_trend,   subset=["Trend"])
    .map(style_earn,    subset=["Days to Earn."] if "Days to Earn." in disp.columns else [])
    .format({
        "Price":        "${:.2f}",
        "1M Strike":    "${:.2f}",
        "3M Strike":    "${:.2f}",
        "1M Delta":     "{:.3f}",
        "3M Delta":     "{:.3f}",
        "1M IV":        "{:.1%}",
        "1M Ann Yield": "{:.1%}",
        "3M Ann Yield": "{:.1%}",
        "1M Cushion":   "{:.1%}",
        "3M Cushion":   "{:.1%}",
        "1M Premium":   "${:.2f}",
        "3M Premium":   "${:.2f}",
        "Score":        "{:.2f}",
    }, na_rep="—")
)

st.markdown(f"**{len(disp)} tickers** shown")
st.dataframe(styled, use_container_width=True, hide_index=True)

# Earnings warnings
if "Days to Earn." in df.columns:
    warn = df[df["Days to Earn."].fillna(999) < 35]
    if not warn.empty:
        st.warning(
            "⚠️  **Earnings inside 35 days:** " +
            ", ".join(f"{r['Ticker']} ({int(r['Days to Earn.'])}d)" for _,r in warn.iterrows()) +
            " — do not sell puts through earnings without a plan.",
            icon="⚠️"
        )

st.markdown("---")
st.caption("Strike selected = put with BS delta closest to band centre (Income: 0.225, Wheel: 0.375). "
           "IV Rank shown after 5+ days of daily snapshots. "
           "Always reconcile with your broker's live chain before trading.")
