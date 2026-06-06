"""
Public Put-Selling Tool — entry point.
Password-protected via st.secrets (SCREENER_PASSWORD).
Pages: Screener, Option Finder.
"""
import streamlit as st

st.set_page_config(
    page_title="Put-Selling Tool",
    page_icon="📊",
    layout="wide",
)

# ── Password gate (shared across all pages via session_state) ─────────────────
PASSWORD = ""
try:
    PASSWORD = st.secrets.get("SCREENER_PASSWORD", "")
except Exception:
    pass

if PASSWORD:
    if not st.session_state.get("authenticated"):
        st.title("📊 Put-Selling Tool")
        pwd = st.text_input("Enter password", type="password")
        if st.button("Login"):
            if pwd == PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.stop()
else:
    st.session_state["authenticated"] = True

st.title("📊 Put-Selling Tool")
st.markdown("Live options data · Refreshes every 5 min · Always reconcile with your broker before trading.")
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.page_link("public_pages/1_Screener.py", label="📋  Screener", icon="📋", use_container_width=True)
    st.caption("Full watchlist — best 1M/3M put per ticker, verdict, filters")
with col2:
    st.page_link("public_pages/2_Option_Finder.py", label="🔍  Option Finder", icon="🔍", use_container_width=True)
    st.caption("Pick any ticker + tenor + delta band → full put chain + roll calculator")
