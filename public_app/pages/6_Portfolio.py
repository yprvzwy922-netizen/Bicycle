"""
Portfolio & Risk — open positions, delta exposure, sector exposure, risk limit gauges.
Reads from the Trade Log session state.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
from shared import (get_watchlist, fetch_spot, bs_put_delta, bs_call_delta)
import datetime

st.set_page_config(page_title="Portfolio & Risk", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c_nav1, _ = st.columns([1, 9])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")

st.title("PORTFOLIO & RISK")
st.caption("OPEN POSITIONS FROM TRADE LOG | DELTA EXPOSURE | SECTOR LIMITS | RISK GAUGES")

# ── Risk limits (sidebar) ─────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### RISK LIMITS")
    TOTAL_CAPITAL   = st.number_input("TOTAL CAPITAL ($)", 10_000, 10_000_000, 100_000, 5_000)
    MAX_SINGLE_NAME = st.slider("MAX SINGLE NAME %",      5,  30, 10) / 100
    MAX_SPECULATIVE = st.slider("MAX SPECULATIVE %",     10,  50, 20) / 100
    MAX_SECTOR      = st.slider("MAX SECTOR %",          10,  50, 25) / 100
    MAX_DEPLOYED    = st.slider("MAX % DEPLOYED",        50, 100, 80) / 100
    MIN_CASH_BUFFER = st.slider("MIN CASH BUFFER %",      5,  40, 20) / 100
    MAX_DELTA_TOTAL = st.number_input("MAX NET DELTA ($ notional)", 0, 10_000_000, 50_000, 5_000,
                                      help="Max total dollar-delta across all positions")
    st.markdown("---")
    st.caption("LIMITS MATCH PUT-SELLING PLAYBOOK DEFAULTS")

# ── Get open trades ───────────────────────────────────────────────────────────
trades = st.session_state.get("trades", pd.DataFrame())

if trades.empty or (trades["STATUS"] == "OPEN").sum() == 0:
    st.info("No open trades in the Trade Log. Add trades in the Trade Log page first.")
    st.markdown("---")
    if st.button("GO TO TRADE LOG", type="primary"):
        st.switch_page("pages/5_Trade_Log.py")
    st.stop()

open_trades = trades[trades["STATUS"] == "OPEN"].copy()
wl = get_watchlist()
wl_map = {w["ticker"]: w for w in wl}

# ── Enrich with live data ─────────────────────────────────────────────────────
rows = []
for _, t in open_trades.iterrows():
    tkr = str(t["TICKER"])
    try:
        spot = fetch_spot(tkr)
    except Exception:
        spot = float("nan")

    # Estimate DTE remaining
    try:
        exp_dt = datetime.datetime.strptime(str(t["EXPIRY"]), "%Y-%m-%d").date()
        dte_rem = max((exp_dt - datetime.date.today()).days, 0)
    except Exception:
        dte_rem = 0

    # Delta estimation
    strat = str(t["STRATEGY"])
    short_strike = float(t["SHORT STRIKE"]) if pd.notna(t["SHORT STRIKE"]) else 0
    long_strike  = float(t["LONG STRIKE"])  if pd.notna(t["LONG STRIKE"])  else 0
    ctrs = int(t["CONTRACTS"])
    prem = float(t["PREMIUM / CREDIT"]) if pd.notna(t["PREMIUM / CREDIT"]) else 0
    iv_est = 0.35  # fallback IV for live delta — use broker for accuracy

    delta = float("nan")
    dollar_delta = float("nan")
    try:
        if "Put" in strat and short_strike > 0:
            d = bs_put_delta(spot, short_strike, iv_est, dte_rem)
            delta = -d  # short put = negative delta
        elif "Call" in strat and short_strike > 0:
            d = bs_call_delta(spot, short_strike, iv_est, dte_rem)
            delta = -d  # short call = negative delta
        if "Spread" in strat and long_strike > 0:
            if "Put" in strat:
                d_long = bs_put_delta(spot, long_strike, iv_est, dte_rem)
                delta = delta + d_long  # long put offsets
            elif "Call" in strat:
                d_long = bs_call_delta(spot, long_strike, iv_est, dte_rem)
                delta = delta + d_long
        dollar_delta = delta * ctrs * 100 * spot if not np.isnan(delta) else float("nan")
    except Exception:
        pass

    # Cash at risk
    cash_sec = float(t["CASH SECURED"]) if pd.notna(t["CASH SECURED"]) else (
        short_strike * 100 * ctrs if short_strike > 0 else 0)
    max_loss = float(t["MAX LOSS"]) if pd.notna(t["MAX LOSS"]) else cash_sec

    # Unrealized P&L (rough: for short options, use intrinsic as floor)
    try:
        if "Put" in strat and short_strike > 0 and not np.isnan(spot):
            intrinsic = max(short_strike - spot, 0)
            curr_val  = intrinsic  # rough
            unreal = (prem - curr_val) * 100 * ctrs
        elif "Call" in strat and short_strike > 0 and not np.isnan(spot):
            intrinsic = max(spot - short_strike, 0)
            curr_val  = intrinsic
            unreal = (prem - curr_val) * 100 * ctrs
        else:
            unreal = float("nan")
    except Exception:
        unreal = float("nan")

    wl_info = wl_map.get(tkr, {})
    rows.append({
        "ID":           t["ID"],
        "TICKER":       tkr,
        "STRATEGY":     strat,
        "SECTOR":       wl_info.get("sector", "Unknown"),
        "BUCKET":       wl_info.get("bucket", "Unknown"),
        "SPOT":         round(spot, 2) if not np.isnan(spot) else None,
        "SHORT STRIKE": short_strike or None,
        "LONG STRIKE":  long_strike or None,
        "EXPIRY":       t["EXPIRY"],
        "DTE LEFT":     dte_rem,
        "CONTRACTS":    ctrs,
        "PREM/CREDIT":  prem,
        "CASH AT RISK": cash_sec,
        "MAX LOSS":     max_loss,
        "DELTA (EST)":  round(delta, 3) if not np.isnan(delta) else None,
        "$ DELTA":      round(dollar_delta, 0) if not np.isnan(dollar_delta) else None,
        "UNREAL PNL":   round(unreal, 2) if not np.isnan(unreal) else None,
    })

book = pd.DataFrame(rows)

# ── Portfolio KPIs ────────────────────────────────────────────────────────────
total_cash    = book["CASH AT RISK"].sum()
total_max_loss= book["MAX LOSS"].sum()
pct_deployed  = total_cash / TOTAL_CAPITAL if TOTAL_CAPITAL else 0
cash_buffer   = 1 - pct_deployed
total_ddelta  = pd.to_numeric(book["$ DELTA"], errors="coerce").sum()
total_unreal  = pd.to_numeric(book["UNREAL PNL"], errors="coerce").sum()

k1,k2,k3,k4,k5 = st.columns(5)
k1.metric("OPEN POSITIONS",    len(book))
k2.metric("CAPITAL DEPLOYED",  f"${total_cash:,.0f}", f"{pct_deployed:.1%}")
k3.metric("TOTAL MAX LOSS",    f"${total_max_loss:,.0f}")
k4.metric("NET $ DELTA",       f"${total_ddelta:,.0f}")
k5.metric("UNREAL PNL (APPROX)", f"${total_unreal:,.0f}")

st.caption("Delta estimated using 35% flat IV proxy — use broker for accurate Greeks.")
st.markdown("---")

# ── Position table ────────────────────────────────────────────────────────────
st.markdown("### OPEN POSITIONS")

def color_dte(v):
    try: return "color:#ff4444;font-weight:600" if int(v) < 14 else "color:#ff9900" if int(v) < 21 else ""
    except: return ""

def color_pnl(v):
    try: return "color:#00e676" if float(v) > 0 else "color:#ff4444" if float(v) < 0 else ""
    except: return ""

styled_book = (book.style
    .map(color_dte,  subset=["DTE LEFT"])
    .map(color_pnl,  subset=["UNREAL PNL"])
    .format({
        "SPOT":         "${:.2f}",
        "SHORT STRIKE": "${:.2f}",
        "LONG STRIKE":  "${:.2f}",
        "PREM/CREDIT":  "${:.2f}",
        "CASH AT RISK": "${:,.0f}",
        "MAX LOSS":     "${:,.0f}",
        "$ DELTA":      "${:,.0f}",
        "UNREAL PNL":   "${:,.0f}",
        "DELTA (EST)":  "{:.3f}",
    }, na_rep="—"))

st.dataframe(styled_book, use_container_width=True, hide_index=True)

st.markdown("---")

# ── Delta exposure by name ────────────────────────────────────────────────────
st.markdown("### DELTA EXPOSURE BY NAME")
delta_by_name = book.groupby("TICKER").agg(
    SECTOR=("SECTOR","first"),
    BUCKET=("BUCKET","first"),
    CASH_AT_RISK=("CASH AT RISK","sum"),
    DOLLAR_DELTA=("$ DELTA","sum"),
    CONTRACTS=("CONTRACTS","sum"),
).reset_index()
delta_by_name["% OF CAPITAL"] = delta_by_name["CASH_AT_RISK"] / TOTAL_CAPITAL
delta_by_name["OVER LIMIT"]   = delta_by_name["% OF CAPITAL"] > MAX_SINGLE_NAME

def color_over(v): return "color:#ff4444;font-weight:600" if v else "color:#00e676"

st.dataframe(
    delta_by_name.style
    .map(color_over, subset=["OVER LIMIT"])
    .format({
        "CASH_AT_RISK":  "${:,.0f}",
        "DOLLAR_DELTA":  "${:,.0f}",
        "% OF CAPITAL":  "{:.1%}",
    }, na_rep="—"),
    use_container_width=True, hide_index=True
)

# ── Delta & cash by sector ────────────────────────────────────────────────────
st.markdown("### EXPOSURE BY SECTOR")
by_sector = book.groupby("SECTOR").agg(
    CASH=("CASH AT RISK","sum"),
    DOLLAR_DELTA=("$ DELTA","sum"),
    POSITIONS=("ID","count"),
).reset_index()
by_sector["% OF CAPITAL"] = by_sector["CASH"] / TOTAL_CAPITAL
by_sector["OVER LIMIT"] = by_sector["% OF CAPITAL"] > MAX_SECTOR

st.dataframe(
    by_sector.style
    .map(color_over, subset=["OVER LIMIT"])
    .format({
        "CASH":         "${:,.0f}",
        "DOLLAR_DELTA": "${:,.0f}",
        "% OF CAPITAL": "{:.1%}",
    }, na_rep="—"),
    use_container_width=True, hide_index=True
)

st.markdown("---")

# ── Risk limit gauges ─────────────────────────────────────────────────────────
st.markdown("### RISK LIMITS — PASS / FAIL")

spec_cash = book[book["BUCKET"] == "Speculative"]["CASH AT RISK"].sum()
spec_pct  = spec_cash / TOTAL_CAPITAL

checks = [
    ("% DEPLOYED",         pct_deployed <= MAX_DEPLOYED,
     f"{pct_deployed:.1%}  vs  {MAX_DEPLOYED:.0%} limit",
     pct_deployed, MAX_DEPLOYED),
    ("CASH BUFFER",        cash_buffer >= MIN_CASH_BUFFER,
     f"{cash_buffer:.1%}  vs  {MIN_CASH_BUFFER:.0%} minimum",
     cash_buffer, MIN_CASH_BUFFER),
    ("SPECULATIVE BUCKET", spec_pct <= MAX_SPECULATIVE,
     f"{spec_pct:.1%}  vs  {MAX_SPECULATIVE:.0%} limit",
     spec_pct, MAX_SPECULATIVE),
    ("NET $ DELTA",        abs(total_ddelta) <= MAX_DELTA_TOTAL,
     f"${abs(total_ddelta):,.0f}  vs  ${MAX_DELTA_TOTAL:,.0f} limit",
     abs(total_ddelta), MAX_DELTA_TOTAL),
]

# Single-name breaches
name_breaches = delta_by_name[delta_by_name["OVER LIMIT"]]
checks.append((
    "SINGLE-NAME LIMITS",
    name_breaches.empty,
    "ALL OK" if name_breaches.empty else
    " | ".join(f"{r['TICKER']} {r['% OF CAPITAL']:.1%}" for _, r in name_breaches.iterrows()),
    None, None
))

# Sector breaches
sector_breaches = by_sector[by_sector["OVER LIMIT"]]
checks.append((
    "SECTOR LIMITS",
    sector_breaches.empty,
    "ALL OK" if sector_breaches.empty else
    " | ".join(f"{r['SECTOR']} {r['% OF CAPITAL']:.1%}" for _, r in sector_breaches.iterrows()),
    None, None
))

all_pass = all(ok for _, ok, _, _, _ in checks)
if all_pass:
    st.success("ALL RISK LIMITS PASS")
else:
    st.error("ONE OR MORE RISK LIMITS BREACHED — REVIEW BELOW")

for label, ok, detail, val, lim in checks:
    c_icon, c_label, c_detail, c_bar = st.columns([0.5, 2, 3, 4])
    c_icon.markdown(
        "<span style='color:#00e676;font-size:1.1rem'>PASS</span>" if ok else
        "<span style='color:#ff4444;font-size:1.1rem;font-weight:600'>FAIL</span>",
        unsafe_allow_html=True)
    c_label.markdown(f"**{label}**")
    c_detail.markdown(f"`{detail}`")
    if val is not None and lim is not None and lim > 0:
        fill = min(val / lim, 1.5)
        bar_color = "#ff4444" if val > lim else "#ff9900" if val > lim * 0.85 else "#00c8ff"
        c_bar.markdown(
            f"""<div style='background:#1a1a1a;height:10px;border:1px solid #222;margin-top:6px'>
            <div style='background:{bar_color};height:10%;width:{fill/1.5*100:.0f}%;'></div>
            </div>""",
            unsafe_allow_html=True)

st.markdown("---")
st.caption("DELTA ESTIMATED WITH 35% FLAT IV — FOR ACCURATE GREEKS USE BROKER | UNREAL PNL = INTRINSIC ONLY APPROXIMATION")
