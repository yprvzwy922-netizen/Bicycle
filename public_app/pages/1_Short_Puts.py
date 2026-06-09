"""
Short Put Screener
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
from shared import (get_watchlist, fetch_spot, fetch_hist, fetch_earnings,
                    best_put, trend_label_score, rv_percentile, score_put,
                    prefetch, SECTORS)

st.set_page_config(page_title="Short Puts", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

# ── Nav ───────────────────────────────────────────────────────────────────────
c_nav1, c_nav2 = st.columns([1, 9])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")

st.title("SHORT PUT SCREENER")
st.caption("STRATEGY: SELL CASH-SECURED PUT | TARGET: OTM STRIKE NEAR DELTA BAND CENTRE | YIELD = ANNUALIZED PREMIUM / STRIKE")

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### FILTERS")
    f_trend    = st.checkbox("TREND UP ONLY", False)
    f_earn     = st.checkbox("NO EARNINGS INSIDE DTE WINDOW", True)
    f_min_yld  = st.number_input("MIN 1M ANN YIELD (%)", min_value=0, max_value=200, value=10, step=5)
    f_min_yld  = f_min_yld / 100
    f_max_delt = st.slider("MAX 1M DELTA", 0.10, 0.60, 0.45, 0.01)
    f_min_oi   = st.number_input("MIN OPEN INTEREST", min_value=0, value=100, step=100)
    f_max_sp   = st.slider("MAX BID/ASK SPREAD %", 0.01, 0.50, 0.20, 0.01)
    f_min_cush = st.slider("MIN DOWNSIDE CUSHION %", 0.0, 0.20, 0.02, 0.005, format="%.1f%%")
    f_buckets  = st.multiselect("BUCKET", ["Core","Growth","Speculative"], default=[])
    f_sectors  = st.multiselect("SECTOR", SECTORS, default=[])
    f_verdict  = st.selectbox("MIN VERDICT", ["PASS","WATCH","TRADE"], index=0)
    st.markdown("---")
    st.caption("TREND = EMA50 vs EMA200 PROXY\nIV RANK = REALIZED VOL PERCENTILE (1Y)\nSCORE = WEIGHTED 1-5 COMPOSITE")

st.markdown(" ")
col_ref, col_btn = st.columns([3,1])
with col_btn:
    if st.button("REFRESH DATA", type="primary", use_container_width=True):
        st.cache_data.clear()

# ── Build rows ────────────────────────────────────────────────────────────────
wl = get_watchlist()
rows, errors = [], []

# Warm all per-ticker caches in parallel first (network-bound) so the loop below
# reads from cache instead of blocking on sequential yfinance calls.
prog = st.progress(0, text="FETCHING MARKET DATA...")
prefetch([w["ticker"] for w in wl], dtes=(35,), option_type="put")

for i, w in enumerate(wl):
    tkr = w["ticker"]
    try:
        spot    = fetch_spot(tkr)
        hist    = fetch_hist(tkr)
        earn    = fetch_earnings(tkr)
        trend, tech_s = trend_label_score(hist)
        ivr     = rv_percentile(hist)
        p1      = best_put(tkr, w["delta_band"], 35)

        ay   = p1.get("ann_yield", float("nan"))
        oi   = p1.get("oi", 0)
        sp   = p1.get("spread_pct", float("nan"))
        dte_t= p1.get("dte", 35) or 35
        sc, vd = score_put(ivr, ay, oi, sp, earn, dte_t, tech_s, w["conviction"])

        earn_warn = isinstance(earn, int) and earn < dte_t

        rows.append({
            "TICKER":        tkr,
            "COMPANY":       w["company"],
            "SECTOR":        w["sector"],
            "BUCKET":        w["bucket"],
            "PRICE":         round(spot, 2),
            "TREND":         trend,
            "IV RANK":       round(ivr, 2),
            "EARN DAYS":     earn if earn is not None else "—",
            "EARN WARN":     earn_warn,
            "BAND":          w["delta_band"],
            "1M STRIKE":     p1.get("strike"),
            "1M DELTA":      p1.get("delta"),
            "1M IV":         p1.get("iv"),
            "1M ANN YLD":    p1.get("ann_yield"),
            "1M CUSHION":    p1.get("cushion"),
            "1M PREMIUM":    p1.get("premium"),
            "1M EXPIRY":     p1.get("expiry"),
            "1M DTE":        p1.get("dte"),
            "1M OI":         p1.get("oi"),
            "STRIKE SCORE":  p1.get("score"),
            "SCORE":         sc,
            "VERDICT":       vd,
        })
    except Exception as e:
        errors.append(f"{tkr}: {e}")
    prog.progress((i+1)/len(wl), text=f"LOADING {tkr}...")

prog.empty()

if errors:
    with st.expander(f"{len(errors)} TICKER(S) WITH ERRORS"):
        for e in errors: st.text(e)

df = pd.DataFrame(rows)
if df.empty:
    st.warning("No data loaded.")
    st.stop()

# ── Apply filters ─────────────────────────────────────────────────────────────
v_ord = {"PASS":0,"WATCH":1,"TRADE":2}
if f_trend:    df = df[df["TREND"].str.startswith("UP", na=False)]
if f_earn:     df = df[~df["EARN WARN"].fillna(False)]
if f_min_yld:  df = df[df["1M ANN YLD"].fillna(0) >= f_min_yld]
if f_max_delt < 0.60: df = df[df["1M DELTA"].fillna(1.0) <= f_max_delt]
if f_min_oi:   df = df[df["1M OI"].fillna(0) >= f_min_oi]
if f_max_sp < 0.50:   df = df[df["1M ANN YLD"].notna()]  # crude proxy for liquid
if f_min_cush: df = df[df["1M CUSHION"].fillna(0) >= f_min_cush]
if f_buckets:  df = df[df["BUCKET"].isin(f_buckets)]
if f_sectors:  df = df[df["SECTOR"].isin(f_sectors)]
if f_verdict != "PASS": df = df[df["VERDICT"].map(v_ord).fillna(0) >= v_ord[f_verdict]]

# ── KPI row ───────────────────────────────────────────────────────────────────
trade_ct = (df["VERDICT"] == "TRADE").sum()
watch_ct = (df["VERDICT"] == "WATCH").sum()
avg_yld  = df["1M ANN YLD"].mean()

k1,k2,k3,k4 = st.columns(4)
k1.metric("TICKERS SHOWN",   len(df))
k2.metric("TRADE VERDICTS",  trade_ct)
k3.metric("WATCH VERDICTS",  watch_ct)
k4.metric("AVG 1M ANN YIELD", f"{avg_yld:.1%}" if not np.isnan(avg_yld) else "—")

st.markdown("---")

# ── Table ─────────────────────────────────────────────────────────────────────
# COMPANY and SECTOR are kept in df for filtering but hidden from the table.
# 3M columns are hidden for now — short put strategy is run on the 1M (35 DTE) tenor.
SHOW = ["TICKER","PRICE","TREND","IV RANK","EARN DAYS","BAND",
        "1M STRIKE","1M DELTA","1M IV","1M ANN YLD","1M CUSHION","1M PREMIUM","1M EXPIRY",
        "STRIKE SCORE","SCORE","VERDICT"]
disp = df[[c for c in SHOW if c in df.columns]].copy()

def sv(v):
    return {"TRADE":"background-color:#0a2a0a;color:#00e676;font-weight:600",
            "WATCH":"background-color:#1a1400;color:#ff9900",
            "PASS": "background-color:#1a0a0a;color:#555555"}.get(str(v),"")

def st_(v):
    if "UP" in str(v): return "color:#00e676"
    if "DOWN" in str(v): return "color:#ff4444"
    return "color:#888888"

def se(v):
    try: return "color:#ff4444;font-weight:600" if int(v) < 35 else ""
    except: return ""

def sivr(v):
    try:
        f = float(v)
        if f >= 0.7: return "color:#00e676;font-weight:600"
        if f >= 0.4: return "color:#ff9900"
        return "color:#888888"
    except: return ""

styled = (disp.style
    .map(sv,   subset=["VERDICT"])
    .map(st_,  subset=["TREND"])
    .map(se,   subset=["EARN DAYS"])
    .map(sivr, subset=["IV RANK"])
    .format({
        "PRICE":     "${:.2f}",
        "IV RANK":   "{:.0%}",
        "1M STRIKE": "${:.2f}",
        "1M DELTA":  "{:.3f}",
        "1M IV":     "{:.1%}",
        "1M ANN YLD":"{:.1%}",
        "1M CUSHION":"{:.1%}",
        "1M PREMIUM":"${:.2f}",
        "STRIKE SCORE":"{:.0f}",
        "SCORE":     "{:.2f}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Earnings warnings ─────────────────────────────────────────────────────────
warn = df[df["EARN WARN"].fillna(False)]
if not warn.empty:
    names = ", ".join(f"{r['TICKER']} ({r['EARN DAYS']}d)" for _,r in warn.iterrows())
    st.warning(f"EARNINGS WARNING: {names} — do not sell puts through earnings without a plan.")

st.markdown("---")
st.caption("1M STRIKE = HIGHEST-SCORING STRIKE IN THE BAND (SAME SCORE AS OPTION FINDER: YIELD + CUSHION + DELTA-FIT + LIQUIDITY), NEAREST EXPIRY TO 35 DTE | "
           "STRIKE SCORE = 0-100 QUALITY OF THAT STRIKE | "
           "EARN DAYS = CALENDAR DAYS TO NEXT EARNINGS (RED = INSIDE 35D WINDOW) | "
           "IV RANK = 1Y REALIZED VOL PERCENTILE (PROXY) | "
           "SCORE + VERDICT (1-5) ARE THE TICKER-LEVEL COMPOSITE ON THE 1M TRADE | "
           "VERDICT THRESHOLD: TRADE >= 3.8 | WATCH >= 3.0 | "
           "ALWAYS RECONCILE WITH BROKER BEFORE TRADING")
