"""
Fund & NAV — unitized multi-investor accounting.

Each contribution buys units at the current NAV/unit, so contributions at
different times are handled fairly. NAV = total contributed + realized P&L +
unrealized P&L. Daily history is written by scripts/daily_snapshot.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import bbg_style
import db
from shared import compute_book_pnl

st.set_page_config(page_title="Fund & NAV", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c_nav1, c_nav2, _ = st.columns([1, 2, 7])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")
with c_nav2:
    if st.button("↻ REFRESH DATA", help="Pull the latest snapshots from Supabase (after a manual run)"):
        db.load_fund_snapshots.clear()
        db.load_portfolio_snapshots.clear()
        st.rerun()

st.title("FUND & NAV")
st.caption("UNITIZED MULTI-INVESTOR FUND | EACH CONTRIBUTION BUYS UNITS AT THE NAV/UNIT OF ITS DATE")

SEED_NAV_PER_UNIT = 100.0   # first contribution prices units at $100 each

# ── Current fund value ────────────────────────────────────────────────────────
trades = db.get_trades_df()
with st.spinner("MARKING BOOK..."):
    realized, unreal = compute_book_pnl(trades)

contribs = db.load_contributions()
total_contributed = float(pd.to_numeric(contribs["amount"], errors="coerce").sum()) if not contribs.empty else 0.0
total_units       = float(pd.to_numeric(contribs["units_issued"], errors="coerce").sum()) if not contribs.empty else 0.0

nav = total_contributed + realized + unreal
nav_per_unit = (nav / total_units) if total_units > 0 else SEED_NAV_PER_UNIT
total_pnl = realized + unreal

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("FUND NAV",        f"${nav:,.0f}")
k2.metric("CONTRIBUTED",     f"${total_contributed:,.0f}")
k3.metric("TOTAL P&L ($)",   f"${total_pnl:,.0f}",
          f"{(total_pnl/total_contributed):+.1%}" if total_contributed > 0 else None,
          help="Realized + unrealized, in dollars (the % is on contributed capital)")
k4.metric("REALIZED P&L",    f"${realized:,.0f}")
k5.metric("UNREALIZED P&L",  f"${unreal:,.0f}")
k6.metric("NAV / UNIT",      f"${nav_per_unit:,.2f}",
          f"{(nav_per_unit/SEED_NAV_PER_UNIT-1):+.1%}" if total_units > 0 else None)

st.markdown("---")

# ── Investors & contributions ─────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.markdown("### INVESTORS")
    investors = db.load_investors()
    ni1, ni2 = st.columns([3, 1])
    new_inv = ni1.text_input("ADD INVESTOR", key="new_inv").strip()
    ni2.markdown(" ")
    if ni2.button("ADD", use_container_width=True) and new_inv:
        db.add_investor(new_inv)
        st.rerun()
    st.caption(", ".join(investors) if investors else "No investors yet.")

with right:
    st.markdown("### LOG A CONTRIBUTION")
    if not investors:
        st.caption("Add an investor first.")
    else:
        cc1, cc2, cc3 = st.columns(3)
        c_inv  = cc1.selectbox("INVESTOR", investors, key="c_inv")
        c_amt  = cc2.number_input("AMOUNT ($)", min_value=0.0, step=1000.0, key="c_amt")
        c_date = cc3.date_input("DATE", datetime.date.today(), key="c_date")
        units_now = c_amt / nav_per_unit if nav_per_unit > 0 else 0
        st.caption(f"At NAV/unit ${nav_per_unit:,.2f} → **{units_now:,.2f} units** issued.")
        if st.button("ADD CONTRIBUTION", type="primary") and c_amt > 0:
            db.add_contribution(c_inv, c_date.isoformat(), c_amt, units_now, nav_per_unit)
            st.success(f"{c_inv} contributed ${c_amt:,.0f} → {units_now:,.2f} units.")
            st.rerun()

st.markdown("---")

# ── Ownership table ───────────────────────────────────────────────────────────
st.markdown("### OWNERSHIP — % OF FUND, VALUE & P&L PER INVESTOR")
if contribs.empty:
    st.info("No contributions yet. Add investors and log their initial capital above.")
else:
    g = contribs.groupby("investor").agg(
        CONTRIBUTED=("amount", "sum"),
        UNITS=("units_issued", "sum"),
    ).reset_index().rename(columns={"investor": "INVESTOR"})
    g["% OF FUND"]   = g["UNITS"] / total_units if total_units else 0
    g["VALUE"]       = g["UNITS"] * nav_per_unit
    g["P&L ($)"]     = g["VALUE"] - g["CONTRIBUTED"]   # dollar gain (timing-weighted)
    g["RETURN %"]    = np.where(g["CONTRIBUTED"] > 0, g["VALUE"] / g["CONTRIBUTED"] - 1, 0)
    g = g.sort_values("% OF FUND", ascending=False)

    # Column order: investor, % of fund, then dollar figures
    g = g[["INVESTOR", "% OF FUND", "CONTRIBUTED", "VALUE", "P&L ($)", "RETURN %", "UNITS"]]

    # TOTAL row
    tot = pd.DataFrame([{
        "INVESTOR": "TOTAL", "% OF FUND": g["% OF FUND"].sum(),
        "CONTRIBUTED": g["CONTRIBUTED"].sum(), "VALUE": g["VALUE"].sum(),
        "P&L ($)": g["P&L ($)"].sum(), "RETURN %": (g["VALUE"].sum()/g["CONTRIBUTED"].sum()-1)
                    if g["CONTRIBUTED"].sum() > 0 else 0,
        "UNITS": g["UNITS"].sum(),
    }])
    g = pd.concat([g, tot], ignore_index=True)

    def color_pnl(v):
        try: return "color:#00e676" if float(v) > 0 else "color:#ff4444" if float(v) < 0 else ""
        except: return ""
    def bold_total(row):
        return ["font-weight:700;border-top:1px solid #00c8ff" if row["INVESTOR"] == "TOTAL" else "" for _ in row]

    st.dataframe(
        g.style.map(color_pnl, subset=["P&L ($)", "RETURN %"])
               .apply(bold_total, axis=1)
               .format({
            "% OF FUND": "{:.1%}", "CONTRIBUTED": "${:,.0f}", "VALUE": "${:,.0f}",
            "P&L ($)": "${:,.0f}", "RETURN %": "{:+.1%}", "UNITS": "{:,.2f}",
        }), use_container_width=True, hide_index=True)
    st.caption("% OF FUND = your units ÷ total units. P&L ($) = current value − what you put in "
               "(timing-weighted via unit accounting). RETURN % = P&L ÷ your contributions.")

    with st.expander("ALL CONTRIBUTIONS"):
        st.dataframe(
            contribs.sort_values("date").style.format({
                "amount": "${:,.0f}", "units_issued": "{:,.2f}", "nav_per_unit": "${:,.2f}",
            }), use_container_width=True, hide_index=True)

# ── History (daily snapshots) ─────────────────────────────────────────────────
if db.configured():
    fs = db.load_fund_snapshots()
    if not fs.empty and "snap_date" in fs.columns:
        fs = fs.sort_values("snap_date").reset_index(drop=True)
        fs["nav"]          = pd.to_numeric(fs["nav"], errors="coerce")
        fs["nav_per_unit"] = pd.to_numeric(fs["nav_per_unit"], errors="coerce")

        st.markdown("---")
        st.markdown("### FUND VALUE ($) — HISTORY")

        # Single clean NAV line. Contributions are shown as vertical tags on their
        # ACTUAL dates (from the contributions table), not derived from the snapshot
        # diff — so they land on the right day and don't overlap the value line.
        fig = go.Figure()
        # Contributions as bars SIZED TO THEIR $ AMOUNT (261k towers over 50k),
        # on their real dates.
        if not contribs.empty and "date" in contribs.columns:
            cby = (contribs.assign(amount=pd.to_numeric(contribs["amount"], errors="coerce"))
                   .groupby("date")["amount"].sum().sort_index())
            dates = [pd.Timestamp(d) for d in cby.index]
            span = (max(dates) - min(dates)).days if len(dates) > 1 else 6
            bar_w = max(1.0, span * 0.04) * 86400000.0     # width in ms, scales with range
            fig.add_bar(x=dates, y=list(cby.values), name="CONTRIBUTIONS",
                        marker_color="rgba(255,153,0,0.45)", width=bar_w,
                        text=[f"+${v:,.0f}" for v in cby.values], textposition="outside",
                        textfont=dict(color="#ff9900", size=10),
                        hovertemplate="Contribution %{x|%b %d}: $%{y:,.0f}<extra></extra>")
        # Fund value (NAV) line on top
        fig.add_scatter(x=[pd.Timestamp(d) for d in fs["snap_date"]], y=fs["nav"],
                        name="FUND VALUE", mode="lines+markers",
                        line=dict(color="#00c8ff", width=2))
        fig.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            legend=dict(orientation="h", y=1.12), barmode="overlay",
            margin=dict(l=40, r=20, t=40, b=40), height=380,
            xaxis=dict(gridcolor="#1e1e1e", type="date", tickformat="%b %d"),
            yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Blue line = total fund value (NAV). Orange bars = cash contributions, "
                   "SIZED to the amount, on the day made. Performance is the NAV/unit chart below.")

        st.markdown("### NAV PER UNIT — HISTORY")
        st.caption("Per-unit value is unaffected by infusions (that's the point of unit accounting) "
                   "— this line is pure performance.")
        fig2 = go.Figure()
        fig2.add_scatter(x=fs["snap_date"], y=fs["nav_per_unit"],
                         mode="lines+markers", line=dict(color="#00e676", width=2))
        fig2.add_hline(y=SEED_NAV_PER_UNIT, line_color="#444444", line_dash="dot")
        fig2.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            margin=dict(l=40, r=20, t=20, b=40), height=320, showlegend=False,
            xaxis=dict(gridcolor="#1e1e1e", type="category"),
            yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.markdown("---")
        st.info("NAV history will appear here once the daily snapshot job has run "
                "(see Phase B setup). Each trading day adds one point.")

st.markdown("---")
st.caption("NAV = CONTRIBUTED + REALIZED + UNREALIZED  |  UNITS PRICED AT NAV/UNIT ON CONTRIBUTION DATE  |  "
           "UNREALIZED MARKED AT LIVE OPTION MID / SPOT")
