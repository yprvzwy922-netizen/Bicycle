"""
Public Option Finder page
"""
import datetime
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from scipy.stats import norm

st.set_page_config(page_title="Option Finder", page_icon="🔍", layout="wide")

if not st.session_state.get("authenticated"):
    st.warning("Please log in from the home page.")
    if st.button("← Go to login"):
        st.switch_page("app.py")
    st.stop()

if st.button("← Home"):
    st.switch_page("app.py")

WATCHLIST_TICKERS = ["IREN","CIFR","NBIS","CRWV","CEG","DGXX","VRT","GEV",
                     "NVDA","MU","AMD","GOOG","BB","LLY","NVO","AMGN","HIMS","VKTX","IBRX"]

# ── Math ──────────────────────────────────────────────────────────────────────
def bs_put_delta(spot, strike, iv, dte, rf=0.053):
    if dte <= 0 or iv <= 0 or spot <= 0 or strike <= 0: return float("nan")
    T = dte / 365.0
    d1 = (np.log(spot/strike) + (rf + 0.5*iv**2)*T) / (iv*np.sqrt(T))
    return abs(norm.cdf(d1) - 1)

def moneyness(spot, strike):
    b = 0.01 * spot
    if strike < spot - b: return "OTM"
    if strike > spot + b: return "ITM"
    return "ATM"

def ann_yield(prem, strike, dte):
    return (prem/strike)*(365/dte) if strike and dte else float("nan")

def ann_roll(net_credit, strike_new, added_dte):
    return (net_credit/strike_new)*(365/added_dte) if strike_new and added_dte else float("nan")

# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_spot(tkr):
    info = yf.Ticker(tkr).fast_info
    p = getattr(info,"last_price",None) or getattr(info,"regularMarketPrice",None)
    if p is None:
        h = yf.Ticker(tkr).history(period="2d")
        p = float(h["Close"].iloc[-1]) if not h.empty else float("nan")
    return float(p)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_chain(tkr, target_dte):
    t = yf.Ticker(tkr)
    exps = list(t.options)
    if not exps: return None, None, None
    today = datetime.date.today()
    best = min(exps, key=lambda e: abs((datetime.datetime.strptime(e,"%Y-%m-%d").date()-today).days - target_dte))
    dte = (datetime.datetime.strptime(best,"%Y-%m-%d").date()-today).days
    chain = t.option_chain(best).puts.copy()
    chain["mid"] = (chain["bid"]+chain["ask"])/2
    chain["spread_pct"] = (chain["ask"]-chain["bid"])/chain["mid"].replace(0,np.nan)
    chain["dte"] = dte
    return chain, best, dte

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🔍 Option Finder")
st.caption("Full put chain for any ticker — pick your tenor and delta band.")

c1, c2, c3, c4 = st.columns([2,2,2,2])
with c1:
    custom = st.text_input("Type any ticker (or pick below)").upper().strip()
    ticker = custom if custom else st.selectbox("Watchlist", WATCHLIST_TICKERS)
with c2:
    tenor = st.selectbox("Tenor", ["1M (~35 DTE)","3M (~90 DTE)","6M (~180 DTE)","Custom"])
    dte_map = {"1M (~35 DTE)":35,"3M (~90 DTE)":90,"6M (~180 DTE)":180}
    target_dte = dte_map.get(tenor, st.number_input("DTE", 7, 365, 35) if tenor=="Custom" else 35)
with c3:
    band = st.selectbox("Delta band", ["Income (0.15–0.30)","Wheel (0.30–0.45)","All"])
    lo = {"Income (0.15–0.30)":0.05,"Wheel (0.30–0.45)":0.20}.get(band, 0.0)
    hi = {"Income (0.15–0.30)":0.45,"Wheel (0.30–0.45)":0.65}.get(band, 1.0)
with c4:
    st.markdown("<br>", unsafe_allow_html=True)
    run = st.button("Load chain", type="primary")

# ── Roll calculator ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔁 Roll Calculator")
    st.caption("Compare rolling vs letting expire.")
    rb  = st.number_input("Buyback premium ($/share)", 0.0, step=0.01, value=0.50)
    rn  = st.number_input("New premium ($/share)",     0.0, step=0.01, value=1.20)
    rsk = st.number_input("New strike",                0.0, step=0.50, value=100.0)
    rd  = st.number_input("DTE remaining (current)",   1,   value=10)
    rnd = st.number_input("DTE (new expiry)",           1,   value=35)
    if rnd > rd and rsk > 0:
        nc = rn - rb
        ar = ann_roll(nc, rsk, rnd - rd)
        st.metric("Ann. roll yield", f"{ar:.1%}")
        st.metric("Net credit / share", f"${nc:.2f}")
    else:
        st.info("New DTE must be greater than remaining DTE.")

if not run:
    st.info("Select a ticker and click **Load chain**.")
    st.stop()

with st.spinner(f"Fetching {ticker}…"):
    spot = fetch_spot(ticker)
    chain, expiry, dte = fetch_chain(ticker, target_dte)

if chain is None or chain.empty:
    st.error("No options data found for this ticker.")
    st.stop()

st.subheader(f"{ticker}  ·  Spot **${spot:.2f}**  ·  Expiry **{expiry}**  ({dte} DTE)")

# Enrich
chain = chain.copy()
chain["delta"]     = chain.apply(lambda r: bs_put_delta(spot, r["strike"], r["impliedVolatility"], dte), axis=1)
chain["moneyness"] = chain["strike"].apply(lambda k: moneyness(spot, k))
chain["ann_yield"] = chain.apply(lambda r: ann_yield(r["mid"], r["strike"], dte), axis=1)
chain["cushion"]   = chain["strike"].apply(lambda k: (spot-k)/spot if spot else float("nan"))
chain["breakeven"] = chain["strike"] - chain["mid"]
chain["eff_entry"] = chain.apply(lambda r: (r["strike"]-r["mid"])/spot - 1 if spot else float("nan"), axis=1)
chain["cash_1ct"]  = chain["strike"] * 100
chain["illiquid"]  = chain["spread_pct"].fillna(1) > 0.10

if band != "All":
    chain = chain[(chain["delta"] >= lo) & (chain["delta"] <= hi)]

if chain.empty:
    st.warning("No strikes in this delta band — try 'All'.")
    st.stop()

COLS = {"strike":"Strike","moneyness":"Moneyness","impliedVolatility":"Impl. Vol",
        "delta":"Delta","bid":"Bid","mid":"Mid","ann_yield":"Ann. Yield",
        "cushion":"Cushion","breakeven":"Breakeven","eff_entry":"Eff. Entry vs Spot",
        "cash_1ct":"Cash Secured (1ct)","openInterest":"OI","volume":"Volume",
        "spread_pct":"Bid/Ask Spread %","illiquid":"Illiquid ⚠️"}
present = [c for c in COLS if c in chain.columns]
disp = chain[present].rename(columns=COLS).copy()

def cm(v): return {"OTM":"background-color:#1a3a1a","ATM":"background-color:#3a3a00","ITM":"background-color:#3a1a1a"}.get(v,"")
def ci(v): return "color:orange;font-weight:bold" if v else ""

styled = (disp.style
    .map(cm, subset=["Moneyness"])
    .map(ci, subset=["Illiquid ⚠️"])
    .format({"Strike":"${:.2f}","Impl. Vol":"{:.1%}","Delta":"{:.3f}",
             "Bid":"${:.2f}","Mid":"${:.2f}","Ann. Yield":"{:.1%}",
             "Cushion":"{:.1%}","Breakeven":"${:.2f}","Eff. Entry vs Spot":"{:.1%}",
             "Cash Secured (1ct)":"${:,.0f}","Bid/Ask Spread %":"{:.1%}"}, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True)

best = chain.sort_values("ann_yield", ascending=False).iloc[0]
st.success(
    f"**Best yield in band:** Strike **${best['strike']:.2f}** · "
    f"Delta **{best['delta']:.3f}** · "
    f"Ann. yield **{best['ann_yield']:.1%}** · "
    f"Cushion **{best['cushion']:.1%}** · "
    f"Breakeven **${best['breakeven']:.2f}**"
)

if chain["illiquid"].any():
    st.warning("⚠️ One or more strikes have bid/ask spread >10% — verify liquidity with your broker.")

st.caption("⚠️ Decision support only. Reconcile with your broker's live chain before submitting any order.")
