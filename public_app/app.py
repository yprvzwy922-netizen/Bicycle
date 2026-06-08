"""
Put-Selling Tool — home page
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import bbg_style

st.set_page_config(page_title="Options Desk", page_icon=None, layout="wide")
bbg_style.inject()

# ── Auth ──────────────────────────────────────────────────────────────────────
PASSWORD = ""
try:
    PASSWORD = st.secrets.get("SCREENER_PASSWORD", "")
except Exception:
    pass

if PASSWORD and not st.session_state.get("authenticated"):
    st.title("OPTIONS DESK")
    st.markdown("---")
    pwd = st.text_input("PASSWORD", type="password")
    if st.button("LOGIN", type="primary"):
        if pwd == PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("INCORRECT PASSWORD")
    st.stop()
else:
    st.session_state["authenticated"] = True

# ── Home ──────────────────────────────────────────────────────────────────────
st.title("OPTIONS DESK")
st.markdown("Live options data via yfinance &nbsp;|&nbsp; 5-min cache &nbsp;|&nbsp; Reconcile with broker before trading",
            unsafe_allow_html=True)
st.markdown("---")

st.markdown("### SELECT A TOOL")
st.markdown(" ")

col1, col2, col3 = st.columns(3, gap="large")

with col1:
    st.markdown("**SHORT PUTS**")
    st.markdown("Sell cash-secured puts on bullish names. Screener + best strike per ticker.")
    if st.button("OPEN SHORT PUT SCREENER", type="primary", use_container_width=True):
        st.switch_page("pages/1_Short_Puts.py")

with col2:
    st.markdown("**COVERED CALLS**")
    st.markdown("Sell OTM calls on positions you hold. Upside cap + annualized yield.")
    if st.button("OPEN COVERED CALL SCREENER", type="primary", use_container_width=True):
        st.switch_page("pages/2_Covered_Calls.py")

with col3:
    st.markdown("**BEAR CALL SPREADS**")
    st.markdown("Sell call spreads on downtrend names. Net credit, max loss, ROC.")
    if st.button("OPEN CALL SPREAD SCREENER", type="primary", use_container_width=True):
        st.switch_page("pages/3_Call_Spreads.py")

st.markdown("---")

col4, col5, col6 = st.columns(3, gap="large")
with col4:
    st.markdown("**OPTION FINDER**")
    st.markdown("Deep-dive chain for any ticker — all strikes, all metrics, roll calculator.")
    if st.button("OPEN OPTION FINDER", type="primary", use_container_width=True):
        st.switch_page("pages/4_Option_Finder.py")

with col5:
    st.markdown("**TRADE LOG**")
    st.markdown("Record every trade — short puts, covered calls, spreads. Export to CSV.")
    if st.button("OPEN TRADE LOG", type="primary", use_container_width=True):
        st.switch_page("pages/5_Trade_Log.py")

with col6:
    st.markdown("**PORTFOLIO & RISK**")
    st.markdown("Open positions, delta exposure by stock and sector, risk limit gauges.")
    if st.button("OPEN PORTFOLIO", type="primary", use_container_width=True):
        st.switch_page("pages/6_Portfolio.py")

st.markdown(" ")
st.caption("DATA: YFINANCE (FREE, BEST-EFFORT) | MATH: BLACK-SCHOLES EUROPEAN APPROX | NOT EXECUTION READY")
