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

bbg_style.inject()


c_nav1, _ = st.columns([1,9])
with c_nav1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")

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
    f_delta    = st.slider("SHORT CALL DELTA (sell leg)", 0.10, 0.50, 0.25, 0.01,
                           help="Target 0.20–0.30 (≈70–80% win prob). Delta ≈ probability the "
                                "short strike finishes ITM. Above ~0.32 the short strike is too close.")
    f_width    = st.slider("SPREAD WIDTH (% of spot)", 0.02, 0.15, 0.06, 0.01, format="%.0f%%")
    f_tenor    = st.selectbox("TENOR", ["1M (~35 DTE)", "3M (~90 DTE)"])
    target_dte = 35 if "1M" in f_tenor else 90

    st.markdown("### SIZING (max-loss based)")
    f_nav      = st.number_input("FUND NAV ($)", min_value=0, value=580000, step=10000)
    f_risk_pct = st.slider("MAX LOSS / TRADE (%)", 0.5, 3.0, 1.5, 0.1,
                           help="Spreads CAN hit full max loss — size by that, not by credit. "
                                "1.5% is tighter than the put per-trade cap on purpose.")
    risk_budget = f_nav * f_risk_pct / 100.0

    st.markdown("### FILTERS")
    f_downtrend= st.checkbox("DOWNTREND / NEUTRAL ONLY", True,
                             help="Bear call spreads want names NOT trending up.")
    f_good_only= st.checkbox("GOOD SETUPS ONLY", False,
                             help="Show only spreads passing both rules: short delta ≤ 0.32 AND "
                                  "credit ≥ ⅓ of width.")
    f_min_roc  = st.number_input("MIN ANN ROC (%)", min_value=0, max_value=300, value=0, step=5)
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
            "EARN DAYS":    float(earn) if earn is not None else np.nan,
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

# ── Quality + sizing (the rules we defined) ───────────────────────────────────
sd = pd.to_numeric(df["SHORT DELTA"], errors="coerce")
cr = pd.to_numeric(df["NET CREDIT"],  errors="coerce")
wd = pd.to_numeric(df["SPREAD WIDTH"],errors="coerce")
ml = pd.to_numeric(df["MAX LOSS"],    errors="coerce")
df["POP"]       = 1 - sd                                   # prob short expires OTM (keep credit)
df["CR/WIDTH"]  = cr / wd                                  # want >= 1/3
df["R:R"]       = ml / cr                                  # risk : reward (want <= 2)
df["CONTRACTS"] = np.floor(risk_budget / (ml * 100)).clip(lower=0)   # sized to max-loss budget

def _quality(d, cw):
    if pd.isna(d) or pd.isna(cw):      return "—"
    if d > 0.32:                       return "TOO CLOSE"      # rule 1: short strike too near
    if cw < 0.30:                      return "SKEWED R:R"     # rule 2: credit < ~⅓ width
    if d < 0.12:                       return "THIN CREDIT"    # too far — negligible premium
    return "GOOD"
df["QUALITY"] = [ _quality(d, cw) for d, cw in zip(sd, df["CR/WIDTH"]) ]

# ── Filters ───────────────────────────────────────────────────────────────────
if f_downtrend: df = df[df["TREND"].isin(["DOWN","NEUTRAL","N/A"])]
if f_good_only: df = df[df["QUALITY"] == "GOOD"]
if f_min_roc:   df = df[df["ANN ROC"].fillna(0) >= f_min_roc]
if f_sectors:   df = df[df["SECTOR"].isin(f_sectors)]

# GOOD setups first, then by score
_qrank = {"GOOD":0, "THIN CREDIT":1, "SKEWED R:R":2, "TOO CLOSE":3, "—":4}
df = df.sort_values(by=["QUALITY","SCORE"],
                    key=lambda s: s.map(_qrank) if s.name == "QUALITY" else -pd.to_numeric(s, errors="coerce"))

# ── KPIs ──────────────────────────────────────────────────────────────────────
good_n  = int((df["QUALITY"] == "GOOD").sum())
avg_roc = df["ANN ROC"].mean()
k1,k2,k3,k4 = st.columns(4)
k1.metric("TICKERS SHOWN",  len(df))
k2.metric("GOOD SETUPS",    good_n, help="Pass both rules: short delta ≤ 0.32 AND credit ≥ ⅓ width")
k3.metric("AVG ANN ROC",    f"{avg_roc:.1%}" if not np.isnan(avg_roc) else "—")
k4.metric("RISK / TRADE",   f"${risk_budget:,.0f}", help=f"{f_risk_pct:.1f}% of ${f_nav:,.0f} NAV — the max-loss budget CONTRACTS is sized to")
if good_n == 0:
    st.warning("NO 'GOOD' SETUPS RIGHT NOW — on high-IV names every strike is either too close "
               "(delta > 0.32) or too skewed (credit < ⅓ width). That usually means the underlyings "
               "are too volatile for bear call spreads; those names are better for SELLING PUTS.")
st.markdown("---")

# ── Table ─────────────────────────────────────────────────────────────────────
# COMPANY and SECTOR kept in df for filtering but hidden from the table
SHOW = ["TICKER","QUALITY","PRICE","TREND","IV RANK",
        "SHORT STRIKE","LONG STRIKE","SHORT DELTA","POP",
        "NET CREDIT","SPREAD WIDTH","CR/WIDTH","MAX LOSS","R:R","CONTRACTS",
        "BREAKEVEN","ROC","ANN ROC","OI","SPREAD","SCORE","EXPIRY"]
disp = df[[c for c in SHOW if c in df.columns]].copy()

def squal(v):
    return {"GOOD":"background-color:#0a2a0a;color:#00e676;font-weight:700",
            "THIN CREDIT":"color:#888888",
            "SKEWED R:R":"background-color:#2a1400;color:#ff9900;font-weight:600",
            "TOO CLOSE":"background-color:#2a0a0a;color:#ff4444;font-weight:600"}.get(str(v),"")
def scw(v):     # credit/width: >=1/3 good, else warn
    try: return "color:#00e676;font-weight:600" if float(v)>=0.33 else "color:#ff4444"
    except: return ""
def srr(v):     # risk:reward: <=2 good
    try: return "color:#00e676;font-weight:600" if float(v)<=2.0 else ("color:#ff9900" if float(v)<=3.5 else "color:#ff4444")
    except: return ""

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
    .map(st_,    subset=["TREND"])
    .map(sivr,   subset=["IV RANK"])
    .map(sroc,   subset=["ANN ROC"])
    .map(ssc,    subset=["SCORE"])
    .map(squal,  subset=["QUALITY"])
    .map(scw,    subset=["CR/WIDTH"])
    .map(srr,    subset=["R:R"])
    .format({
        "PRICE":        "${:.2f}",
        "IV RANK":      "{:.0%}",
        "SHORT STRIKE": "${:.2f}",
        "LONG STRIKE":  "${:.2f}",
        "SHORT DELTA":  "{:.2f}",
        "POP":          "{:.0%}",
        "NET CREDIT":   "${:.2f}",
        "SPREAD WIDTH": "${:.2f}",
        "CR/WIDTH":     "{:.0%}",
        "MAX LOSS":     "${:.2f}",
        "R:R":          "{:.1f}",
        "CONTRACTS":    "{:.0f}",
        "BREAKEVEN":    "${:.2f}",
        "ROC":          "{:.1%}",
        "ANN ROC":      "{:.1%}",
        "SPREAD":       "{:.1%}",
        "SCORE":        "{:.0f}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True,
             column_config={"TICKER": st.column_config.Column(pinned=True),
                            "QUALITY": st.column_config.Column(pinned=True)})

# ── Earnings warning ──────────────────────────────────────────────────────────
try:
    warn = df[pd.to_numeric(df["EARN DAYS"], errors="coerce").fillna(999) < 35]
    if not warn.empty:
        names = ", ".join(f"{r['TICKER']} ({r['EARN DAYS']}d)" for _,r in warn.iterrows())
        st.warning(f"EARNINGS WITHIN 35 DAYS: {names} — spreads can blow out on earnings gaps.")
except Exception:
    pass

st.markdown("---")
st.markdown("""
**How to read this — the rules we use:**
- **QUALITY** — a spread is **GOOD** only if it passes *both*: **short delta ≤ 0.32** (≈ ≥68% win prob — not too close to the money) **AND** **CR/WIDTH ≥ ⅓** (credit is at least a third of the width, so you never risk worse than ~2:1). `TOO CLOSE` = short strike too near; `SKEWED R:R` = credit too small for the width; `THIN CREDIT` = so far OTM the premium is negligible.
- **POP** = probability the short strike expires OTM (you keep the credit) ≈ 1 − short delta.
- **R:R** = max loss ÷ credit. Want **≤ 2**. Your NBIS 300/400 example was ~11:1 → the tool flags it red.
- **CONTRACTS** = sized to your **max-loss budget** (NAV × % in the sidebar), because a spread can go to full max loss — *never* size by credit or notional.
- **Notional is irrelevant** for defined-risk spreads — ignore it; only max loss and probability matter.
- Best on **downtrend / moderate-IV** names. If everything shows red, the names are too volatile for call spreads → **sell puts instead.** Always reconcile with the broker.
""")
