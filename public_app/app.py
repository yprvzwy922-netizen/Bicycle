"""
Options Desk — entrypoint / router.
Central password gate + grouped sidebar navigation (st.navigation).
Home content lives in pages/0_Home.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import bbg_style

st.set_page_config(page_title="Options Desk", page_icon=None, layout="wide")
bbg_style.inject()

# ── Auth (guards every page — pages no longer need their own gate) ────────────
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

# ── Grouped navigation ────────────────────────────────────────────────────────
nav = st.navigation({
    "HOME": [
        st.Page("pages/0_Home.py",         title="Home", default=True),
    ],
    "SCREENERS": [
        st.Page("pages/1_Short_Puts.py",   title="Short Puts"),
        st.Page("pages/2_Covered_Calls.py",title="Covered Calls"),
        st.Page("pages/3_Call_Spreads.py", title="Call Spreads"),
    ],
    "TRADING": [
        st.Page("pages/4_Option_Finder.py",title="Option Finder"),
        st.Page("pages/9_Roll_Finder.py",  title="Roll Finder"),
        st.Page("pages/8_Order_Ticket.py", title="Order Ticket"),
        st.Page("pages/5_Trade_Log.py",    title="Trade Log"),
    ],
    "FUND": [
        st.Page("pages/6_Portfolio.py",    title="Portfolio & Risk"),
        st.Page("pages/7_Fund.py",         title="Fund & NAV"),
    ],
})
nav.run()
