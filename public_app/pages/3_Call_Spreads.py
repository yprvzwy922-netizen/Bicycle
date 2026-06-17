"""
Bear Call Spread Screener
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
from shared import (get_watchlist, fetch_spot, fetch_hist, fetch_earnings,
                    best_bear_call_spread, trend_label_score, rv_percentile,
                    prefetch, SECTORS)

st.set_page_config(page_title="Call Spreads", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c_nav1, _ = st.columns([1,9])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")

st.title("BEAR CALL SPREAD SCREENER")
st.caption("STRATEGY: SELL LOWER STRIKE CALL + BUY HIGHER STRIKE CALL | MAX PROFIT = NET CREDIT | MAX LOSS = SPREAD WIDTH - CREDIT")

st.markdown("""
**How to read this screen:**
A bear call spread collects a net credit by selling a call at a lower strike and buying a call at a higher strike.
Your maximum profit is the credit received (if the stock stays below the short strike at expiry).
Your maximum loss is capped at the spread width minus the credit.
Best used on names in a **downtrend or neutral** environment where you expect the stock to stay flat or fall.
""")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### PARAMETERS")
    f_delta    = st.slider("SHORT CALL DELTA (sell leg)", 0.15, 0.50, 0.30, 0.01,
                           help="Higher delta = more premium but higher probability of loss")
    f_width    = st.slider("SPREAD WIDTH (% of spot)", 0.02, 0.15, 0.05, 0.01, format="%.0f%%")
    f_tenor    = st.selectbox("TENOR", ["1M (~35 DTE)", "3M (~90 DTE)"])
    target_dte = 35 if "1M" in f_tenor else 90
    st.markdown("### FILTERS")
    f_downtrend= st.checkbox("DOWNTREND / NEUTRAL ONLY", True,
                             help="Show only names trending down or neutral")
    f_min_roc  = st.number_input("MIN ANN ROC (%)", min_value=0, max_value=300, value=20, step=5)
    f_min_roc  = f_min_roc / 100
    f_sectors  = st.multiselect("SECTOR", SECTORS, default=[])
    st.markdown("---")
    if st.button("REFRESH", type="primary", use_container_width=True):
        st.cache_data.clear()

# ── Build rows ────────────────────────────────────────────────────────────────
wl = get_watchlist()
rows, errors = [], []
prog = st.progress(0, text="FETCHING MARKET DATA...")
prefetch([w["ticker"] for w in wl], dtes=(target_dte,), option_type="call")

for i, w in enumerate(wl):
    tkr = w["ticker"]
    try:
        spot  = fetch_spot(tkr)
        hist  = fetch_hist(tkr)
        earn  = fetch_earnings(tkr)
        trend, _ = trend_label_score(hist)
        ivr   = rv_percentile(hist)
        cs    = best_bear_call_spread(tkr, f_delta, f_width, target_dte)
        if not cs: continue

        rows.append({
            "TICKER":       tkr,
            "COMPANY":      w["company"],
            "SECTOR":       w["sector"],
            "PRICE":        round(spot, 2),
            "TREND":        trend,
            "IV RANK":      round(ivr, 2),
            "EARN DAYS":    earn if earn is not None else "—",
            "SHORT STRIKE": cs.get("short_strike"),
            "LONG STRIKE":  cs.get("long_strike"),
            "SHORT DELTA":  cs.get("short_delta"),
            "SHORT IV":     cs.get("short_iv"),
            "NET CREDIT":   cs.get("net_credit"),
            "SPREAD WIDTH": cs.get("spread_width"),
            "MAX LOSS":     cs.get("max_loss"),
            "BREAKEVEN":    cs.get("breakeven"),
            "ROC":          cs.get("roc"),
            "ANN ROC":      cs.get("ann_roc"),
            "OI":           cs.get("oi"),
            "SPREAD":       cs.get("spread_pct"),
            "SCORE":        cs.get("score"),
            "EXPIRY":       cs.get("expiry"),
            "DTE":          cs.get("dte"),
        })
    except Exception as e:
        errors.append(f"{tkr}: {e}")
    prog.progress((i+1)/len(wl), text=f"LOADING {tkr}...")

prog.empty()
if errors:
    with st.expander(f"{len(errors)} ERRORS"): [st.text(e) for e in errors]

df = pd.DataFrame(rows)
if df.empty:
    st.warning("No data loaded.")
    st.stop()

# ── Filters ───────────────────────────────────────────────────────────────────
if f_downtrend: df = df[df["TREND"].isin(["DOWN","NEUTRAL","N/A"])]
if f_min_roc:   df = df[df["ANN ROC"].fillna(0) >= f_min_roc]
if f_sectors:   df = df[df["SECTOR"].isin(f_sectors)]

# ── KPIs ──────────────────────────────────────────────────────────────────────
avg_roc = df["ANN ROC"].mean()
avg_cr  = df["NET CREDIT"].mean()
k1,k2,k3 = st.columns(3)
k1.metric("TICKERS SHOWN",    len(df))
k2.metric("AVG ANN ROC",      f"{avg_roc:.1%}" if not np.isnan(avg_roc) else "—")
k3.metric("AVG NET CREDIT",   f"${avg_cr:.2f}" if not np.isnan(avg_cr) else "—")
st.markdown("---")

# ── Table ─────────────────────────────────────────────────────────────────────
# COMPANY and SECTOR kept in df for filtering but hidden from the table
SHOW = ["TICKER","PRICE","TREND","IV RANK","EARN DAYS",
        "SHORT STRIKE","LONG STRIKE","SHORT DELTA","SHORT IV",
        "NET CREDIT","SPREAD WIDTH","MAX LOSS","BREAKEVEN","ROC","ANN ROC",
        "OI","SPREAD","SCORE","EXPIRY"]
disp = df[[c for c in SHOW if c in df.columns]].copy()

def st_(v):
    if "DOWN" in str(v): return "color:#ff4444"
    if "UP" in str(v):   return "color:#888888"
    return "color:#aaaaaa"

def sroc(v):
    try:
        f = float(v)
        if f >= 0.60: return "color:#00e676;font-weight:600"
        if f >= 0.30: return "color:#ff9900"
        return ""
    except: return ""

def sivr(v):
    try:
        f = float(v)
        if f >= 0.7: return "color:#00e676;font-weight:600"
        if f >= 0.4: return "color:#ff9900"
        return "color:#888888"
    except: return ""

def ssc(v):
    try:
        f = float(v)
        return "color:#00e676;font-weight:700" if f>=75 else "color:#00c8ff;font-weight:600" if f>=50 else "color:#888888"
    except: return ""

styled = (disp.style
    .map(st_,  subset=["TREND"])
    .map(sivr, subset=["IV RANK"])
    .map(sroc, subset=["ANN ROC"])
    .map(ssc,  subset=["SCORE"])
    .format({
        "PRICE":        "${:.2f}",
        "IV RANK":      "{:.0%}",
        "SHORT STRIKE": "${:.2f}",
        "LONG STRIKE":  "${:.2f}",
        "SHORT DELTA":  "{:.3f}",
        "SHORT IV":     "{:.1%}",
        "NET CREDIT":   "${:.2f}",
        "SPREAD WIDTH": "${:.2f}",
        "MAX LOSS":     "${:.2f}",
        "BREAKEVEN":    "${:.2f}",
        "ROC":          "{:.1%}",
        "ANN ROC":      "{:.1%}",
        "SPREAD":       "{:.1%}",
        "SCORE":        "{:.0f}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Earnings warning ──────────────────────────────────────────────────────────
try:
    warn = df[pd.to_numeric(df["EARN DAYS"], errors="coerce").fillna(999) < 35]
    if not warn.empty:
        names = ", ".join(f"{r['TICKER']} ({r['EARN DAYS']}d)" for _,r in warn.iterrows())
        st.warning(f"EARNINGS WITHIN 35 DAYS: {names} — spreads can blow out on earnings gaps.")
except Exception:
    pass

st.markdown("---")
st.caption("ROC = NET CREDIT / MAX LOSS | ANN ROC = ROC * 365/DTE | MAX LOSS IS CAPPED AT SPREAD WIDTH - CREDIT | ALWAYS RECONCILE WITH BROKER")
