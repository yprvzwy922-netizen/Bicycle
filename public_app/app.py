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

st.markdown("""
### 👈 Use the arrow in the top-left corner to open the menu, then choose:

| | Page | What it does |
|---|---|---|
| 📋 | **Screener** | Full watchlist — best 1M/3M put per ticker, verdict, filters |
| 🔍 | **Option Finder** | Pick any ticker + tenor + delta band → full put chain + roll calculator |
""")
