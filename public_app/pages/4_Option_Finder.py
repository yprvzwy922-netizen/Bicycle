"""
Option Finder — deep dive on any ticker, with watchlist management
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import bbg_style
from shared import (get_watchlist, add_to_watchlist, remove_from_watchlist,
                    fetch_spot, fetch_chain, bs_put_delta, bs_call_delta,
                    ann_yield, ann_roll, moneyness, SECTORS)

st.set_page_config(page_title="Option Finder", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c_nav1, _ = st.columns([1,9])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")

st.title("OPTION FINDER")
st.caption("FULL CHAIN FOR ANY TICKER | ALL STRIKES | ALL METRICS | ROLL CALCULATOR")

# ── Watchlist quick-select buttons ────────────────────────────────────────────
wl = get_watchlist()
wl_tickers = [w["ticker"] for w in wl]

st.markdown("### QUICK SELECT")
# Display as a grid of buttons — 10 per row
cols_per_row = 10
rows_needed  = (len(wl_tickers) + cols_per_row - 1) // cols_per_row

selected_ticker = st.session_state.get("finder_ticker", "")

for row_i in range(rows_needed):
    btn_cols = st.columns(cols_per_row)
    for col_i, col in enumerate(btn_cols):
        idx = row_i * cols_per_row + col_i
        if idx < len(wl_tickers):
            tkr = wl_tickers[idx]
            is_sel = tkr == selected_ticker
            label = f"[ {tkr} ]" if is_sel else tkr
            if col.button(label, key=f"qb_{tkr}", use_container_width=True,
                          type="primary" if is_sel else "secondary"):
                st.session_state["finder_ticker"] = tkr
                st.rerun()
        elif idx == len(wl_tickers):
            # "+" quick-add button at the end of the last ticker
            if col.button("＋", key="qb_plus", use_container_width=True,
                          help="Quick-add a new ticker to the watchlist",
                          type="secondary"):
                st.session_state["show_quick_add"] = True

# Quick-add inline form (shows below grid when "+" is pressed)
if st.session_state.get("show_quick_add"):
    with st.container():
        st.markdown("**QUICK ADD TICKER TO WATCHLIST**")
        qa1, qa2, qa3, qa4, qa5, qa6, qa7 = st.columns([2,2,2,2,1,1,1])
        qa_tick = qa1.text_input("TICKER", key="qa_tick").upper().strip()
        qa_co   = qa2.text_input("COMPANY NAME", key="qa_co")
        qa_sec  = qa3.selectbox("SECTOR", SECTORS, key="qa_sec")
        qa_bkt  = qa4.selectbox("BUCKET", ["Core","Growth","Speculative"], key="qa_bkt")
        qa_conv = qa5.number_input("CONVICTION", 1, 5, 3, key="qa_conv")
        qa_band = qa6.selectbox("BAND", ["Income","Wheel"], key="qa_band")
        qa7.markdown(" ")
        qa7.markdown(" ")
        if qa7.button("ADD", type="primary", use_container_width=True) and qa_tick:
            add_to_watchlist(qa_tick, qa_co, qa_sec, qa_bkt, qa_conv, qa_band)
            st.session_state["finder_ticker"] = qa_tick
            st.session_state["show_quick_add"] = False
            st.success(f"{qa_tick} added to watchlist.")
            st.rerun()

st.markdown("---")

# ── Controls ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns([2,2,2,2,1])
with c1:
    custom = st.text_input("TYPE ANY TICKER", value=st.session_state.get("finder_ticker","")).upper().strip()
    if custom: st.session_state["finder_ticker"] = custom
    ticker = st.session_state.get("finder_ticker", "")
with c2:
    tenor = st.selectbox("TENOR", ["1M (~35 DTE)","3M (~90 DTE)","6M (~180 DTE)","CUSTOM"])
    dte_map = {"1M (~35 DTE)":35,"3M (~90 DTE)":90,"6M (~180 DTE)":180}
    target_dte = dte_map.get(tenor, st.number_input("DTE", 7, 365, 35) if tenor=="CUSTOM" else 35)
with c3:
    opt_type = st.selectbox("OPTION TYPE", ["PUTS","CALLS"])
with c4:
    band_label = st.selectbox("DELTA BAND", ["INCOME 0.15-0.30","WHEEL 0.30-0.45","ALL"])
    lo = {"INCOME 0.15-0.30":0.05,"WHEEL 0.30-0.45":0.20}.get(band_label, 0.0)
    hi = {"INCOME 0.15-0.30":0.45,"WHEEL 0.30-0.45":0.65}.get(band_label, 1.0)
with c5:
    st.markdown(" ")
    st.markdown(" ")
    run = st.button("LOAD", type="primary", use_container_width=True)

# ── Watchlist management ──────────────────────────────────────────────────────
with st.expander("MANAGE WATCHLIST (add / remove)"):
    st.caption("Changes apply for this session only. Reload the page to reset to defaults.")
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    m_tick = mc1.text_input("TICKER", key="m_tick").upper()
    m_co   = mc2.text_input("COMPANY", key="m_co")
    m_sec  = mc3.selectbox("SECTOR", SECTORS, key="m_sec")
    m_bkt  = mc4.selectbox("BUCKET", ["Core","Growth","Speculative"], key="m_bkt")
    m_conv = mc5.slider("CONVICTION", 1, 5, 3, key="m_conv")
    m_band = mc6.selectbox("BAND", ["Income","Wheel"], key="m_band")
    col_add, col_rem = st.columns(2)
    with col_add:
        if st.button("ADD TO WATCHLIST", use_container_width=True) and m_tick:
            add_to_watchlist(m_tick, m_co, m_sec, m_bkt, m_conv, m_band)
            st.success(f"{m_tick} added.")
            st.rerun()
    with col_rem:
        rem_tick = st.selectbox("REMOVE", [""] + wl_tickers, key="rem_tick")
        if st.button("REMOVE FROM WATCHLIST", use_container_width=True) and rem_tick:
            remove_from_watchlist(rem_tick)
            st.success(f"{rem_tick} removed.")
            st.rerun()

# ── Roll calculator sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ROLL CALCULATOR")
    st.caption("Annualized yield of rolling a short position to a later expiry.")
    rb   = st.number_input("BUYBACK PREMIUM ($/SHARE)", 0.0, step=0.01, value=0.50)
    rn   = st.number_input("NEW PREMIUM ($/SHARE)",     0.0, step=0.01, value=1.20)
    rsk  = st.number_input("NEW STRIKE",                0.0, step=0.50, value=100.0)
    rd   = st.number_input("DTE REMAINING",             1,   value=10)
    rnd  = st.number_input("NEW EXPIRY DTE",            1,   value=35)
    if rnd > rd and rsk > 0:
        nc = rn - rb
        ar = ann_roll(nc, rsk, rnd - rd)
        st.metric("ANN ROLL YIELD", f"{ar:.1%}")
        st.metric("NET CREDIT / SHARE", f"${nc:.2f}")
        st.metric("NET CREDIT / CONTRACT", f"${nc*100:.2f}")
    else:
        st.caption("Set new DTE > remaining DTE to compute.")

if not ticker:
    st.info("SELECT A TICKER ABOVE OR TYPE ONE IN THE BOX, THEN CLICK LOAD.")
    st.stop()

if not run:
    st.info(f"TICKER: {ticker} — CLICK LOAD TO FETCH CHAIN.")
    st.stop()

# ── Fetch chain ───────────────────────────────────────────────────────────────
with st.spinner(f"FETCHING {ticker}..."):
    spot = fetch_spot(ticker)
    opt  = "put" if opt_type == "PUTS" else "call"
    chain, expiry, dte = fetch_chain(ticker, target_dte, opt)

if chain is None or chain.empty:
    st.error(f"No options data found for {ticker}.")
    st.stop()

st.markdown(f"### {ticker}  |  SPOT: ${spot:.2f}  |  EXPIRY: {expiry}  |  DTE: {dte}")
st.markdown("---")

# ── Enrich ────────────────────────────────────────────────────────────────────
chain = chain[chain["impliedVolatility"] > 0].copy()

if opt == "put":
    chain["delta"]   = chain.apply(
        lambda r: bs_put_delta(spot, r["strike"], r["impliedVolatility"], dte), axis=1)
else:
    chain["delta"]   = chain.apply(
        lambda r: bs_call_delta(spot, r["strike"], r["impliedVolatility"], dte), axis=1)

chain["moneyness"]    = chain["strike"].apply(lambda k: moneyness(spot, k, opt=="put"))
chain["ann_yield"]    = chain.apply(lambda r: ann_yield(r["mid"], r["strike"], dte), axis=1)
chain["cushion_pct"]  = chain["strike"].apply(
    lambda k: (spot-k)/spot if opt=="put" else (k-spot)/spot)
chain["breakeven"]    = chain["strike"] - chain["mid"] if opt == "put" else chain["strike"] + chain["mid"]
chain["eff_entry"]    = chain.apply(
    lambda r: (r["strike"]-r["mid"])/spot - 1 if opt=="put" else (r["strike"]+r["mid"])/spot - 1, axis=1)
chain["cash_1ct"]     = chain["strike"] * 100
chain["illiquid"]     = chain["spread_pct"].fillna(1) > 0.10

# Delta band filter
if band_label != "ALL":
    chain = chain[(chain["delta"] >= lo) & (chain["delta"] <= hi)]

if chain.empty:
    st.warning("NO STRIKES IN THIS DELTA BAND. TRY 'ALL'.")
    st.stop()

# ── Display ───────────────────────────────────────────────────────────────────
COLS = {
    "strike":          "STRIKE",
    "moneyness":       "MONEYNESS",
    "impliedVolatility":"IV",
    "delta":           "DELTA",
    "bid":             "BID",
    "mid":             "MID",
    "ann_yield":       "ANN YIELD",
    "cushion_pct":     "CUSHION / UPSIDE",
    "breakeven":       "BREAKEVEN",
    "eff_entry":       "EFF ENTRY VS SPOT",
    "cash_1ct":        "CASH SECURED (1CT)",
    "openInterest":    "OI",
    "volume":          "VOLUME",
    "spread_pct":      "SPREAD %",
    "illiquid":        "ILLIQUID",
}
present = [c for c in COLS if c in chain.columns]
disp = chain[present].rename(columns=COLS).copy()

def cm(v):
    return {"OTM":"background-color:#0a1a0a","ATM":"background-color:#1a1400",
            "ITM":"background-color:#1a0a0a"}.get(v,"")
def ci(v): return "color:#ff9900;font-weight:600" if v else ""

styled = (disp.style
    .map(cm, subset=["MONEYNESS"])
    .map(ci, subset=["ILLIQUID"])
    .format({
        "STRIKE":           "${:.2f}",
        "IV":               "{:.1%}",
        "DELTA":            "{:.3f}",
        "BID":              "${:.2f}",
        "MID":              "${:.2f}",
        "ANN YIELD":        "{:.1%}",
        "CUSHION / UPSIDE": "{:.1%}",
        "BREAKEVEN":        "${:.2f}",
        "EFF ENTRY VS SPOT":"{:.1%}",
        "CASH SECURED (1CT)":"${:,.0f}",
        "SPREAD %":         "{:.1%}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Best strike highlight ─────────────────────────────────────────────────────
best = chain.sort_values("ann_yield", ascending=False).iloc[0]
st.success(
    f"BEST YIELD IN BAND:  "
    f"STRIKE ${best['strike']:.2f}  |  "
    f"DELTA {best['delta']:.3f}  |  "
    f"ANN YIELD {best['ann_yield']:.1%}  |  "
    f"CUSHION {best['cushion_pct']:.1%}  |  "
    f"BREAKEVEN ${best['breakeven']:.2f}"
)

if chain["illiquid"].any():
    st.warning("ONE OR MORE STRIKES HAVE BID/ASK SPREAD > 10% — VERIFY LIQUIDITY WITH BROKER.")

st.markdown("---")
st.caption("DECISION SUPPORT ONLY | ALWAYS RECONCILE PREMIUM, IV, AND DELTA WITH BROKER LIVE CHAIN BEFORE TRADING")
