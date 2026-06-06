"""
Covered Call Screener
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
from shared import (get_watchlist, fetch_spot, fetch_hist, fetch_earnings,
                    best_call, trend_label_score, rv_percentile, SECTORS)

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
st.caption("STRATEGY: SELL OTM CALL ON OWNED STOCK | YIELD = PREMIUM / SPOT PRICE | UPSIDE CAP = (STRIKE - SPOT) / SPOT")

st.markdown("""
**How to read this screen:**
Sell a covered call by writing a call option against stock you already own.
You collect the premium immediately. If the stock stays below the strike at expiry, you keep the premium.
If it rises above, you sell your stock at the strike — you still profit up to that level plus the premium.
Best used on names you own in a **sideways to mildly bullish** environment.
""")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### FILTERS")
    f_delta    = st.slider("TARGET CALL DELTA", 0.10, 0.50, 0.25, 0.01,
                           help="0.20-0.30 = conservative, 0.30-0.40 = aggressive")
    f_tenor    = st.selectbox("TENOR", ["1M (~35 DTE)", "3M (~90 DTE)"])
    target_dte = 35 if "1M" in f_tenor else 90
    f_min_yld  = st.number_input("MIN ANN YIELD (%)", min_value=0, max_value=200, value=8, step=2)
    f_min_yld  = f_min_yld / 100
    f_min_cap  = st.slider("MIN UPSIDE CAP %", 0.0, 0.30, 0.02, 0.005, format="%.1f%%")
    f_sectors  = st.multiselect("SECTOR", SECTORS, default=[])
    f_buckets  = st.multiselect("BUCKET", ["Core","Growth","Speculative"], default=[])
    st.markdown("---")
    if st.button("REFRESH", type="primary", use_container_width=True):
        st.cache_data.clear()

# ── Build rows ────────────────────────────────────────────────────────────────
wl = get_watchlist()
rows, errors = [], []
prog = st.progress(0, text="LOADING...")

for i, w in enumerate(wl):
    tkr = w["ticker"]
    try:
        spot  = fetch_spot(tkr)
        hist  = fetch_hist(tkr)
        earn  = fetch_earnings(tkr)
        trend, _ = trend_label_score(hist)
        ivr   = rv_percentile(hist)
        cc    = best_call(tkr, f_delta, target_dte)
        if not cc: continue

        rows.append({
            "TICKER":      tkr,
            "COMPANY":     w["company"],
            "SECTOR":      w["sector"],
            "BUCKET":      w["bucket"],
            "PRICE":       round(spot, 2),
            "TREND":       trend,
            "IV RANK":     round(ivr, 2),
            "EARN DAYS":   earn if earn is not None else "—",
            "CALL STRIKE": cc.get("strike"),
            "CALL DELTA":  cc.get("delta"),
            "CALL IV":     cc.get("iv"),
            "PREMIUM":     cc.get("premium"),
            "ANN YIELD":   cc.get("ann_yield"),
            "UPSIDE CAP":  cc.get("upside_cap"),
            "BREAKEVEN UP":cc.get("breakeven_up"),
            "OI":          cc.get("oi"),
            "EXPIRY":      cc.get("expiry"),
            "DTE":         cc.get("dte"),
            "ILLIQUID":    "YES" if not np.isnan(cc.get("spread_pct", 0) or 0) and cc.get("spread_pct", 0) > 0.10 else "",
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
if f_min_yld:  df = df[df["ANN YIELD"].fillna(0) >= f_min_yld]
if f_min_cap:  df = df[df["UPSIDE CAP"].fillna(0) >= f_min_cap]
if f_sectors:  df = df[df["SECTOR"].isin(f_sectors)]
if f_buckets:  df = df[df["BUCKET"].isin(f_buckets)]

# ── KPIs ──────────────────────────────────────────────────────────────────────
avg_yld = df["ANN YIELD"].mean()
avg_cap = df["UPSIDE CAP"].mean()
k1,k2,k3 = st.columns(3)
k1.metric("TICKERS SHOWN", len(df))
k2.metric("AVG ANN YIELD", f"{avg_yld:.1%}" if not np.isnan(avg_yld) else "—")
k3.metric("AVG UPSIDE CAP", f"{avg_cap:.1%}" if not np.isnan(avg_cap) else "—")
st.markdown("---")

# ── Table ─────────────────────────────────────────────────────────────────────
SHOW = ["TICKER","COMPANY","SECTOR","PRICE","TREND","IV RANK","EARN DAYS",
        "CALL STRIKE","CALL DELTA","CALL IV","PREMIUM","ANN YIELD","UPSIDE CAP","BREAKEVEN UP","OI","EXPIRY","ILLIQUID"]
disp = df[[c for c in SHOW if c in df.columns]].copy()

def st_(v):
    if "UP" in str(v): return "color:#00e676"
    if "DOWN" in str(v): return "color:#ff4444"
    return "color:#888888"

def ill(v): return "color:#ff9900;font-weight:600" if v == "YES" else ""

def sivr(v):
    try:
        f = float(v)
        if f >= 0.7: return "color:#00e676;font-weight:600"
        if f >= 0.4: return "color:#ff9900"
        return "color:#888888"
    except: return ""

styled = (disp.style
    .map(st_,  subset=["TREND"])
    .map(sivr, subset=["IV RANK"])
    .map(ill,  subset=["ILLIQUID"])
    .format({
        "PRICE":       "${:.2f}",
        "IV RANK":     "{:.0%}",
        "CALL STRIKE": "${:.2f}",
        "CALL DELTA":  "{:.3f}",
        "CALL IV":     "{:.1%}",
        "PREMIUM":     "${:.2f}",
        "ANN YIELD":   "{:.1%}",
        "UPSIDE CAP":  "{:.1%}",
        "BREAKEVEN UP":"${:.2f}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Earnings warning ──────────────────────────────────────────────────────────
try:
    warn = df[pd.to_numeric(df["EARN DAYS"], errors="coerce").fillna(999) < 35]
    if not warn.empty:
        names = ", ".join(f"{r['TICKER']} ({r['EARN DAYS']}d)" for _,r in warn.iterrows())
        st.warning(f"EARNINGS WITHIN 35 DAYS: {names} — covered calls through earnings carry gap risk.")
except Exception:
    pass

st.markdown("---")
st.caption("YIELD = PREMIUM / SPOT (not strike) | UPSIDE CAP = max gain if called away | ALWAYS RECONCILE WITH BROKER")
