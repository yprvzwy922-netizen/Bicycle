"""
Covered Call Screener — recommends calls ONLY on stock you hold in the book.
Wheel names -> lower-delta calls (keep upside); Income names -> higher-delta
calls (more premium, get called away and recycle).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
import db
from shared import (get_watchlist, fetch_spot, fetch_hist, fetch_earnings,
                    best_call, trend_label_score, rv_percentile, prefetch)

st.set_page_config(page_title="Covered Calls", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c_nav1, _ = st.columns([1,9])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")

st.title("COVERED CALL SCREENER")
st.caption("SELLS CALLS ONLY ON STOCK YOU HOLD | WHEEL = LOWER DELTA (KEEP UPSIDE) | INCOME = HIGHER DELTA (GET CALLED AWAY)")

# ── Track-based delta targets (manual + your spec) ────────────────────────────
with st.sidebar:
    st.markdown("### TARGET CALL DELTA")
    WHEEL_DELTA  = st.slider("WHEEL NAMES",  0.10, 0.40, 0.20, 0.01,
                             help="High-conviction names you want to keep — lower delta, more upside")
    INCOME_DELTA = st.slider("INCOME NAMES", 0.20, 0.50, 0.35, 0.01,
                             help="Names you want called away to recycle — higher delta, more premium")
    f_tenor    = st.selectbox("TENOR", ["1M (~35 DTE)", "3M (~90 DTE)"])
    target_dte = 35 if "1M" in f_tenor else 90
    st.markdown("---")
    if st.button("REFRESH", type="primary", use_container_width=True):
        st.cache_data.clear()

# ── Held stock = Long Stock positions in the book ─────────────────────────────
trades = db.get_trades_df()
held = pd.DataFrame()
if not trades.empty:
    held = trades[(trades["STATUS"] == "OPEN") & (trades["STRATEGY"] == "Long Stock")].copy()

if held.empty:
    st.info("No stock held. Covered calls only apply to shares you own — get assigned on a put "
            "(Trade Log) or add a Long Stock position, then come back.")
    if st.button("GO TO TRADE LOG", type="primary"):
        st.switch_page("pages/5_Trade_Log.py")
    st.stop()

# Shares held per ticker + track from the watchlist
shares_by_tkr = held.groupby("TICKER")["CONTRACTS"].sum().to_dict()
wl_map = {w["ticker"]: w for w in get_watchlist()}

prog = st.progress(0, text="FETCHING MARKET DATA...")
tickers = list(shares_by_tkr.keys())
prefetch(tickers, dtes=(target_dte,), option_type="call")

rows, errors = [], []
for i, tkr in enumerate(tickers):
    try:
        info  = wl_map.get(tkr, {})
        track = info.get("delta_band", "Income")
        tgt   = WHEEL_DELTA if track == "Wheel" else INCOME_DELTA
        spot  = fetch_spot(tkr)
        hist  = fetch_hist(tkr)
        earn  = fetch_earnings(tkr)
        trend, _ = trend_label_score(hist)
        ivr   = rv_percentile(hist)
        cc    = best_call(tkr, tgt, target_dte)
        if not cc:
            continue
        shares    = int(shares_by_tkr[tkr])
        max_calls = shares // 100
        rows.append({
            "TICKER":     tkr,
            "SECTOR":     info.get("sector", "Unknown"),
            "TRACK":      track,
            "SHARES":     shares,
            "MAX CALLS":  max_calls,
            "PRICE":      round(spot, 2),
            "TREND":      trend,
            "IV RANK":    round(ivr, 2),
            "EARN DAYS":  float(earn) if earn is not None else np.nan,
            "STRIKE":     cc.get("strike"),
            "DELTA":      cc.get("delta"),
            "TGT DELTA":  round(tgt, 2),
            "IV":         cc.get("iv"),
            "PREMIUM":    cc.get("premium"),
            "ANN YIELD":  cc.get("ann_yield"),
            "UPSIDE CAP": cc.get("upside_cap"),
            "OI":         cc.get("oi"),
            "SPREAD":     cc.get("spread_pct"),
            "SCORE":      cc.get("score"),
            "EXPIRY":     cc.get("expiry"),
        })
    except Exception as e:
        errors.append(f"{tkr}: {e}")
    prog.progress((i+1)/len(tickers), text=f"LOADING {tkr}...")
prog.empty()

if errors:
    with st.expander(f"{len(errors)} ERRORS"): [st.text(e) for e in errors]

df = pd.DataFrame(rows)
if df.empty:
    st.warning("No call data loaded for held names.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
k1,k2,k3 = st.columns(3)
k1.metric("HELD NAMES", len(df))
k2.metric("AVG ANN YIELD", f"{df['ANN YIELD'].mean():.1%}")
k3.metric("AVG UPSIDE CAP", f"{df['UPSIDE CAP'].mean():.1%}")
st.markdown("---")

# ── Table (unified layout) ────────────────────────────────────────────────────
SHOW = ["TICKER","TRACK","SHARES","MAX CALLS","PRICE","TREND","IV RANK","EARN DAYS",
        "STRIKE","DELTA","TGT DELTA","IV","PREMIUM","ANN YIELD","UPSIDE CAP",
        "OI","SPREAD","SCORE","EXPIRY"]
disp = df[[c for c in SHOW if c in df.columns]].copy()

def st_(v):
    if "UP" in str(v): return "color:#00e676"
    if "DOWN" in str(v): return "color:#ff4444"
    return "color:#888888"
def sivr(v):
    try:
        f = float(v)
        return "color:#00e676;font-weight:600" if f>=0.7 else "color:#ff9900" if f>=0.4 else "color:#888888"
    except: return ""
def ssc(v):
    try:
        f = float(v)
        return "color:#00e676;font-weight:700" if f>=75 else "color:#00c8ff;font-weight:600" if f>=50 else "color:#888888"
    except: return ""
def strk(v):
    return "color:#00c8ff" if str(v)=="Wheel" else "color:#ff9900"

styled = (disp.style
    .map(st_,   subset=["TREND"])
    .map(sivr,  subset=["IV RANK"])
    .map(ssc,   subset=["SCORE"])
    .map(strk,  subset=["TRACK"])
    .format({
        "PRICE":"${:.2f}", "IV RANK":"{:.0%}", "EARN DAYS":"{:.0f}", "STRIKE":"${:.2f}",
        "DELTA":"{:.3f}", "TGT DELTA":"{:.2f}", "IV":"{:.1%}", "PREMIUM":"${:.2f}",
        "ANN YIELD":"{:.1%}", "UPSIDE CAP":"{:.1%}", "SPREAD":"{:.1%}", "SCORE":"{:.0f}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True)

warn = df[pd.to_numeric(df["EARN DAYS"], errors="coerce").fillna(999) < 35]
if not warn.empty:
    names = ", ".join(f"{r['TICKER']} ({r['EARN DAYS']}d)" for _,r in warn.iterrows())
    st.warning(f"EARNINGS WITHIN 35 DAYS: {names} — covered calls through earnings carry gap risk.")

st.markdown("---")
st.caption("YIELD = PREMIUM / SPOT | UPSIDE CAP = max gain if called away | MAX CALLS = shares // 100 | "
           "SCORE = yield + upside-room + delta-fit + liquidity | ALWAYS RECONCILE WITH BROKER")
