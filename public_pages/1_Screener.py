"""
Public Screener page
"""
import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from scipy.stats import norm

st.set_page_config(page_title="Screener", page_icon="📋", layout="wide")

# ── Auth guard ────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated"):
    st.warning("Please log in from the home page.")
    st.stop()

# ── Watchlist ─────────────────────────────────────────────────────────────────
WATCHLIST = [
    {"ticker": "IREN",  "company": "IREN Ltd",               "sector": "AI data center",          "bucket": "Growth",      "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "CIFR",  "company": "Cipher Digital",          "sector": "Crypto / HPC",            "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "NBIS",  "company": "Nebius Group",            "sector": "AI data center",          "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CRWV",  "company": "CoreWeave",               "sector": "AI data center",          "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CEG",   "company": "Constellation Energy",    "sector": "Power / nuclear",         "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "DGXX",  "company": "Digi Power X",            "sector": "Energy / AI data center", "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "VRT",   "company": "Vertiv",                  "sector": "Power / DC equip",        "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "GEV",   "company": "GE Vernova",              "sector": "Power / grid equip",      "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVDA",  "company": "NVIDIA",                  "sector": "AI compute / semis",      "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MU",    "company": "Micron",                  "sector": "AI compute / semis",      "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMD",   "company": "Advanced Micro Devices",  "sector": "AI compute / semis",      "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "GOOG",  "company": "Alphabet",                "sector": "Comm services",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "BB",    "company": "BlackBerry",              "sector": "Software / security",     "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "LLY",   "company": "Eli Lilly",               "sector": "Healthcare / peptides",   "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVO",   "company": "Novo Nordisk",            "sector": "Healthcare / peptides",   "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMGN",  "company": "Amgen",                   "sector": "Healthcare / pharma",     "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "HIMS",  "company": "Hims & Hers",             "sector": "Healthcare / telehealth", "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "VKTX",  "company": "Viking Therapeutics",     "sector": "Healthcare / peptides",   "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "IBRX",  "company": "ImmunityBio",             "sector": "Healthcare / biotech",    "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
]

# ── Math ──────────────────────────────────────────────────────────────────────
def bs_put_delta(spot, strike, iv, dte, rf=0.053):
    if dte <= 0 or iv <= 0 or spot <= 0 or strike <= 0: return float("nan")
    T = dte / 365.0
    d1 = (np.log(spot / strike) + (rf + 0.5*iv**2)*T) / (iv*np.sqrt(T))
    return abs(norm.cdf(d1) - 1)

def ann_yield(premium, strike, dte):
    return (premium / strike) * (365 / dte) if strike and dte else float("nan")

def cushion(spot, strike):
    return (spot - strike) / spot if spot else float("nan")

def score_verdict(ivr_s, yld_s, liq_s, earn_s, tech_s, conv_s):
    s = 0.30*ivr_s + 0.25*yld_s + 0.15*liq_s + 0.10*earn_s + 0.10*tech_s + 0.10*conv_s
    v = "TRADE" if s >= 4 else ("Watch" if s >= 3 else "Pass")
    return round(s, 2), v

# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_spot(tkr):
    info = yf.Ticker(tkr).fast_info
    p = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
    if p is None:
        h = yf.Ticker(tkr).history(period="2d")
        p = float(h["Close"].iloc[-1]) if not h.empty else float("nan")
    return float(p)

@st.cache_data(ttl=600, show_spinner=False)
def fetch_hist(tkr):
    return yf.Ticker(tkr).history(period="1y")

@st.cache_data(ttl=300, show_spinner=False)
def fetch_best_put(tkr, delta_band, target_dte):
    lo, hi = (0.15, 0.30) if delta_band == "Income" else (0.30, 0.45)
    target = (lo + hi) / 2
    spot = fetch_spot(tkr)
    t = yf.Ticker(tkr)
    exps = list(t.options)
    if not exps: return {}
    today = datetime.date.today()
    best_exp = min(exps, key=lambda e: abs((datetime.datetime.strptime(e,"%Y-%m-%d").date()-today).days - target_dte))
    dte = (datetime.datetime.strptime(best_exp,"%Y-%m-%d").date()-today).days
    chain = t.option_chain(best_exp).puts.copy()
    chain = chain[chain["impliedVolatility"] > 0]
    if chain.empty: return {}
    chain["mid"] = (chain["bid"] + chain["ask"]) / 2
    chain["delta"] = chain.apply(lambda r: bs_put_delta(spot, r["strike"], r["impliedVolatility"], dte), axis=1)
    sub = chain[(chain["delta"] >= lo*0.6) & (chain["delta"] <= hi*1.6)]
    if sub.empty: sub = chain
    sub = sub.copy()
    sub["dist"] = (sub["delta"] - target).abs()
    row = sub.loc[sub["dist"].idxmin()]
    prem = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
    strike = float(row["strike"])
    sp = float((row["ask"]-row["bid"])/row["mid"]) if row["mid"] > 0 else float("nan")
    return {"expiry": best_exp, "dte": dte, "strike": strike,
            "delta": round(float(row["delta"]),3), "iv": round(float(row["impliedVolatility"]),4),
            "premium": round(prem,2), "ann_yield": round(ann_yield(prem,strike,dte),4),
            "cushion": round(cushion(spot,strike),4), "breakeven": round(strike-prem,2),
            "oi": int(row.get("openInterest",0) or 0), "spread_pct": round(sp,3)}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings(tkr):
    try:
        ed = yf.Ticker(tkr).earnings_dates
        if ed is not None and not ed.empty:
            idx = ed.index.tz_localize(None) if ed.index.tz else ed.index
            future = ed[idx > pd.Timestamp.now()]
            if not future.empty:
                return (future.index[0].tz_localize(None).date() - datetime.date.today()).days
    except Exception: pass
    return None

def trend_score(tkr):
    hist = fetch_hist(tkr)
    if hist.empty or len(hist) < 20: return "Unknown", 2.5
    c = hist["Close"]
    e50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    e200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
    p = c.iloc[-1]
    if p > e50 > e200: return "↑ Up", 5.0
    if p > e200:       return "↑ Weak", 3.5
    return "↓ Down", 1.5

def build_row(w):
    tkr = w["ticker"]
    spot = fetch_spot(tkr)
    p1 = fetch_best_put(tkr, w["delta_band"], 35)
    p3 = fetch_best_put(tkr, w["delta_band"], 90)
    trend, tech_s = trend_score(tkr)
    earn = fetch_earnings(tkr)
    ay = p1.get("ann_yield", float("nan"))
    oi = p1.get("oi", 0)
    sp = p1.get("spread_pct", float("nan"))
    dte_t = p1.get("dte", 35) or 35
    yld_s = (5 if not np.isnan(ay) and ay>=0.30 else 4 if ay>=0.20 else 3 if ay>=0.12 else 2 if ay>=0.06 else 1) if not np.isnan(ay) else 1
    liq_s = max(1, min(5, 3 + (1 if oi>5000 else -1 if oi<500 else 0) + (1 if not np.isnan(sp) and sp<0.03 else -1 if not np.isnan(sp) and sp>0.10 else 0)))
    earn_s = 5 if earn is None or earn > dte_t+5 else 4 if earn > dte_t else 2 if earn > 7 else 1
    sc, vd = score_verdict(2.5, yld_s, liq_s, earn_s, tech_s, float(w["conviction"]))
    return {"Ticker": tkr, "Company": w["company"], "Sector": w["sector"], "Bucket": w["bucket"],
            "Price": round(spot,2), "Trend": trend, "Days to Earn.": earn, "Band": w["delta_band"],
            "1M Strike": p1.get("strike"), "1M Delta": p1.get("delta"), "1M IV": p1.get("iv"),
            "1M Ann Yield": p1.get("ann_yield"), "1M Cushion": p1.get("cushion"),
            "1M Premium": p1.get("premium"), "1M Expiry": p1.get("expiry"),
            "3M Strike": p3.get("strike"), "3M Delta": p3.get("delta"),
            "3M Ann Yield": p3.get("ann_yield"), "3M Cushion": p3.get("cushion"),
            "3M Premium": p3.get("premium"),
            "Score": sc, "Verdict": vd,
            "Illiquid": "⚠️" if not np.isnan(sp) and sp > 0.10 else ""}

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    f_trend   = st.checkbox("Trend Up only", False)
    f_earn    = st.checkbox("No earnings inside DTE window", True)
    f_yld     = st.slider("Min 1M ann. yield", 0.0, 0.50, 0.06, 0.01, format="%.0f%%")
    f_delta   = st.slider("Max 1M delta", 0.10, 0.60, 0.45, 0.01)
    f_buckets = st.multiselect("Buckets", ["Core","Growth","Speculative"], default=[])
    f_sectors = st.multiselect("Sectors", sorted(set(w["sector"] for w in WATCHLIST)), default=[])
    f_verdict = st.selectbox("Min verdict", ["Pass","Watch","TRADE"], index=0)

st.title("📋 Screener")
st.caption("Live yfinance data · 5-min cache · Strike = delta closest to band centre")

if st.button("🔄  Refresh", type="primary"):
    st.cache_data.clear()

rows, errors = [], []
prog = st.progress(0, text="Loading…")
for i, w in enumerate(WATCHLIST):
    try:    rows.append(build_row(w))
    except Exception as e: errors.append(f"{w['ticker']}: {e}")
    prog.progress((i+1)/len(WATCHLIST), text=f"Loading {w['ticker']}…")
prog.empty()

if errors:
    with st.expander(f"⚠️ {len(errors)} error(s)"):
        [st.text(e) for e in errors]

df = pd.DataFrame(rows)
v_ord = {"Pass":0,"Watch":1,"TRADE":2}
if f_trend:   df = df[df["Trend"].str.contains("Up", na=False)]
if f_earn and "Days to Earn." in df.columns:
    df = df[df["Days to Earn."].isna() | (df["Days to Earn."] > 35)]
if f_yld > 0: df = df[df["1M Ann Yield"].fillna(0) >= f_yld]
if f_delta < 0.60: df = df[df["1M Delta"].fillna(1.0) <= f_delta]
if f_buckets: df = df[df["Bucket"].isin(f_buckets)]
if f_sectors: df = df[df["Sector"].isin(f_sectors)]
if f_verdict != "Pass": df = df[df["Verdict"].map(v_ord).fillna(0) >= v_ord[f_verdict]]

def sv(v): return {"TRADE":"background-color:#1a6b1a;color:white","Watch":"background-color:#7a6000;color:white","Pass":"background-color:#4a1a1a;color:white"}.get(v,"")
def st_(v): return ("color:#4caf50;font-weight:bold" if "Up" in str(v) else "color:#f44336" if "Down" in str(v) else "")
def se(v):
    try: return "color:red;font-weight:bold" if int(v) < 35 else ""
    except: return ""

SHOW = ["Ticker","Company","Sector","Bucket","Price","Trend","Days to Earn.","Band",
        "1M Strike","1M Delta","1M IV","1M Ann Yield","1M Cushion","1M Premium","1M Expiry",
        "3M Strike","3M Delta","3M Ann Yield","3M Cushion","3M Premium","Score","Verdict","Illiquid"]
disp = df[[c for c in SHOW if c in df.columns]].copy()

styled = (disp.style
    .map(sv, subset=["Verdict"])
    .map(st_, subset=["Trend"])
    .map(se, subset=["Days to Earn."] if "Days to Earn." in disp.columns else [])
    .format({"Price":"${:.2f}","1M Strike":"${:.2f}","3M Strike":"${:.2f}",
             "1M Delta":"{:.3f}","3M Delta":"{:.3f}","1M IV":"{:.1%}",
             "1M Ann Yield":"{:.1%}","3M Ann Yield":"{:.1%}",
             "1M Cushion":"{:.1%}","3M Cushion":"{:.1%}",
             "1M Premium":"${:.2f}","3M Premium":"${:.2f}","Score":"{:.2f}"}, na_rep="—"))

st.markdown(f"**{len(disp)} tickers shown**")
st.dataframe(styled, use_container_width=True, hide_index=True)

warn = df[df["Days to Earn."].fillna(999) < 35]
if not warn.empty:
    st.warning("⚠️ Earnings inside 35 days: " +
               ", ".join(f"{r['Ticker']} ({int(r['Days to Earn.'])}d)" for _,r in warn.iterrows()) +
               " — do not sell puts through earnings without a plan.")
st.caption("Always reconcile with your broker's live chain before trading.")
