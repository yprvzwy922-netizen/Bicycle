"""
Home — tool tiles. (Navigation itself lives in app.py via st.navigation.)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import bbg_style

bbg_style.inject()

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
    st.markdown("Deep-dive chain for any ticker — all strikes, all metrics.")
    if st.button("OPEN OPTION FINDER", type="primary", use_container_width=True):
        st.switch_page("pages/4_Option_Finder.py")
with col5:
    st.markdown("**ROLL FINDER**")
    st.markdown("Roll an open short — scored candidates, net credit at mid vs cross.")
    if st.button("OPEN ROLL FINDER", type="primary", use_container_width=True):
        st.switch_page("pages/9_Roll_Finder.py")
with col6:
    st.markdown("**ORDER TICKET**")
    st.markdown("Collect the strikes you picked into one broker-ready message.")
    if st.button("OPEN ORDER TICKET", type="primary", use_container_width=True):
        st.switch_page("pages/8_Order_Ticket.py")

st.markdown("---")

col7, col8, col9 = st.columns(3, gap="large")
with col7:
    st.markdown("**TRADE LOG**")
    st.markdown("Record every trade — short puts, covered calls, spreads. Export to CSV.")
    if st.button("OPEN TRADE LOG", type="primary", use_container_width=True):
        st.switch_page("pages/5_Trade_Log.py")
with col8:
    st.markdown("**PORTFOLIO & RISK**")
    st.markdown("Open positions, delta exposure by stock and sector, risk limit gauges.")
    if st.button("OPEN PORTFOLIO", type="primary", use_container_width=True):
        st.switch_page("pages/6_Portfolio.py")
with col9:
    st.markdown("**FUND & NAV**")
    st.markdown("Multi-investor unitized fund — contributions, ownership %, NAV history.")
    if st.button("OPEN FUND & NAV", type="primary", use_container_width=True):
        st.switch_page("pages/7_Fund.py")

st.markdown(" ")
st.caption("DATA: YFINANCE (FREE, BEST-EFFORT) | MATH: BLACK-SCHOLES EUROPEAN APPROX | NOT EXECUTION READY")
