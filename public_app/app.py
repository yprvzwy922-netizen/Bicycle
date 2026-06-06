"""
Public Put-Selling Tool — entry point.
Password-protected via st.secrets (SCREENER_PASSWORD).
"""
import streamlit as st

st.set_page_config(
    page_title="Put-Selling Tool",
    page_icon="📊",
    layout="wide",
)

# ── Password gate ─────────────────────────────────────────────────────────────
PASSWORD = ""
try:
    PASSWORD = st.secrets.get("SCREENER_PASSWORD", "")
except Exception:
    pass

if PASSWORD:
    if not st.session_state.get("authenticated"):
        st.title("📊 Put-Selling Tool")
        st.markdown("###")
        pwd = st.text_input("Enter password", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.stop()
else:
    st.session_state["authenticated"] = True

# ── Home page with big navigation buttons ────────────────────────────────────
st.title("📊 Put-Selling Tool")
st.caption("Live options data via yfinance · Always reconcile with your broker before trading.")
st.markdown("---")
st.markdown("### Where would you like to go?")
st.markdown("###")

col1, col2 = st.columns(2, gap="large")

with col1:
    st.markdown("#### 📋 Screener")
    st.markdown("Full watchlist — best 1M/3M put per ticker, verdict, and filters.")
    if st.button("Open Screener →", type="primary", use_container_width=True, key="go_screener"):
        st.switch_page("pages/1_Screener.py")

with col2:
    st.markdown("#### 🔍 Option Finder")
    st.markdown("Pick any ticker + tenor + delta band → full put chain with roll calculator.")
    if st.button("Open Option Finder →", type="primary", use_container_width=True, key="go_finder"):
        st.switch_page("pages/2_Option_Finder.py")
