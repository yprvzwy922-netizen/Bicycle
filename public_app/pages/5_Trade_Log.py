"""
Trade Log — record all trades, export/import CSV for persistence between sessions.
Supports: Short Put, Covered Call, Bear Call Spread, Bull Put Spread, Long Put, Long Call.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
import io
import numpy as np
import pandas as pd
import streamlit as st
import bbg_style

st.set_page_config(page_title="Trade Log", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c_nav1, _ = st.columns([1, 9])
with c_nav1:
    if st.button("HOME"): st.switch_page("app.py")

st.title("TRADE LOG")
st.caption("ALL STRATEGIES | EXPORT CSV TO SAVE | IMPORT CSV TO RESTORE BETWEEN SESSIONS")

# ── Session trade store ───────────────────────────────────────────────────────
COLUMNS = [
    "ID", "DATE OPENED", "TICKER", "STRATEGY",
    "SHORT STRIKE", "LONG STRIKE", "EXPIRY", "DTE OPEN",
    "CONTRACTS", "PREMIUM / CREDIT", "CASH SECURED", "MAX LOSS",
    "STATUS", "DATE CLOSED", "CLOSE PRICE", "REALIZED PNL", "NOTES"
]

def empty_df():
    return pd.DataFrame(columns=COLUMNS)

if "trades" not in st.session_state:
    st.session_state["trades"] = empty_df()

trades: pd.DataFrame = st.session_state["trades"]

# ── Import / Export ───────────────────────────────────────────────────────────
col_imp, col_exp, _ = st.columns([2, 2, 6])

with col_imp:
    uploaded = st.file_uploader("IMPORT CSV", type="csv", label_visibility="collapsed",
                                help="Upload a previously exported trade log CSV")
    if uploaded:
        try:
            loaded = pd.read_csv(uploaded)
            st.session_state["trades"] = loaded
            st.success(f"Loaded {len(loaded)} trades.")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to load: {e}")

with col_exp:
    st.markdown(" ")
    if not trades.empty:
        csv_bytes = trades.to_csv(index=False).encode()
        st.download_button(
            "EXPORT CSV",
            data=csv_bytes,
            file_name=f"trade_log_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

st.markdown("---")

# ── Add trade form ────────────────────────────────────────────────────────────
st.markdown("### NEW TRADE")

STRATEGIES = [
    "Short Put",
    "Covered Call",
    "Bear Call Spread",
    "Bull Put Spread",
    "Long Put (Hedge)",
    "Long Call",
    "Cash-Secured Put (Wheel)",
]

with st.form("new_trade_form", clear_on_submit=True):
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    date_opened = r1c1.date_input("DATE OPENED", datetime.date.today())
    ticker      = r1c2.text_input("TICKER").upper().strip()
    strategy    = r1c3.selectbox("STRATEGY", STRATEGIES)
    contracts   = r1c4.number_input("CONTRACTS", min_value=1, value=1)

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    short_strike = r2c1.number_input("SHORT STRIKE (sell leg)", min_value=0.0, step=0.50)
    long_strike  = r2c2.number_input("LONG STRIKE (buy leg — spreads only)", min_value=0.0, step=0.50,
                                     help="Leave 0 for single-leg trades")
    expiry       = r2c3.text_input("EXPIRY (YYYY-MM-DD)")
    dte_open     = r2c4.number_input("DTE AT OPEN", min_value=1, max_value=365, value=35)

    r3c1, r3c2, r3c3, r3c4 = st.columns(4)
    premium      = r3c1.number_input("PREMIUM / NET CREDIT (per share)", min_value=0.0, step=0.01,
                                     help="For spreads: net credit received per share")
    cash_secured = r3c2.number_input("CASH SECURED ($)", min_value=0.0, step=100.0,
                                     help="For puts: strike × 100 × contracts")
    max_loss_in  = r3c3.number_input("MAX LOSS ($)", min_value=0.0, step=100.0,
                                     help="For spreads: (width - credit) × 100 × contracts")
    notes        = r3c4.text_input("NOTES / SIGNAL TAG")

    submitted = st.form_submit_button("ADD TRADE", type="primary", use_container_width=True)

if submitted and ticker:
    # Auto-calculate cash secured and max loss for common cases
    if cash_secured == 0 and strategy in ["Short Put", "Cash-Secured Put (Wheel)"]:
        cash_secured = short_strike * 100 * contracts
    if max_loss_in == 0 and long_strike > 0:
        spread_w = abs(long_strike - short_strike)
        max_loss_in = (spread_w - premium) * 100 * contracts

    new_id = len(trades) + 1
    new_row = {
        "ID":               new_id,
        "DATE OPENED":      date_opened.isoformat(),
        "TICKER":           ticker,
        "STRATEGY":         strategy,
        "SHORT STRIKE":     short_strike if short_strike > 0 else None,
        "LONG STRIKE":      long_strike if long_strike > 0 else None,
        "EXPIRY":           expiry,
        "DTE OPEN":         dte_open,
        "CONTRACTS":        contracts,
        "PREMIUM / CREDIT": premium,
        "CASH SECURED":     cash_secured if cash_secured > 0 else None,
        "MAX LOSS":         max_loss_in if max_loss_in > 0 else None,
        "STATUS":           "OPEN",
        "DATE CLOSED":      None,
        "CLOSE PRICE":      None,
        "REALIZED PNL":     None,
        "NOTES":            notes,
    }
    st.session_state["trades"] = pd.concat(
        [trades, pd.DataFrame([new_row])], ignore_index=True)
    st.success(f"Trade added: {strategy} on {ticker}")
    st.rerun()

# ── Close a trade ─────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### CLOSE / EXPIRE A TRADE")

open_trades = trades[trades["STATUS"] == "OPEN"] if not trades.empty else empty_df()

if not open_trades.empty:
    with st.form("close_trade_form", clear_on_submit=True):
        cc1, cc2, cc3, cc4 = st.columns(4)
        close_id     = cc1.selectbox("TRADE ID TO CLOSE",
                                     options=open_trades["ID"].tolist(),
                                     format_func=lambda i: f"#{i} {open_trades[open_trades['ID']==i]['TICKER'].values[0]} {open_trades[open_trades['ID']==i]['STRATEGY'].values[0]}")
        close_status = cc2.selectbox("OUTCOME", ["EXPIRED (FULL PROFIT)", "CLOSED EARLY", "ASSIGNED / EXERCISED", "ROLLED"])
        close_price  = cc3.number_input("CLOSE / BUYBACK PRICE (per share)", min_value=0.0, step=0.01)
        close_date   = cc4.date_input("DATE CLOSED", datetime.date.today())

        close_sub = st.form_submit_button("CLOSE TRADE", type="primary", use_container_width=True)

    if close_sub:
        row = trades[trades["ID"] == close_id].iloc[0]
        prem_orig = float(row["PREMIUM / CREDIT"] or 0)
        ctrs = int(row["CONTRACTS"])
        is_short = row["STRATEGY"] not in ["Long Put (Hedge)", "Long Call"]
        if is_short:
            realized = (prem_orig - close_price) * 100 * ctrs
        else:
            realized = (close_price - prem_orig) * 100 * ctrs

        idx = trades[trades["ID"] == close_id].index[0]
        trades.at[idx, "STATUS"]       = close_status
        trades.at[idx, "DATE CLOSED"]  = close_date.isoformat()
        trades.at[idx, "CLOSE PRICE"]  = close_price
        trades.at[idx, "REALIZED PNL"] = round(realized, 2)
        st.session_state["trades"] = trades
        st.success(f"Trade #{close_id} closed. Realized P&L: ${realized:,.2f}")
        st.rerun()
else:
    st.caption("No open trades to close.")

# ── Summary KPIs ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### SUMMARY")

if not trades.empty:
    open_ct   = (trades["STATUS"] == "OPEN").sum()
    closed_ct = (trades["STATUS"] != "OPEN").sum()
    total_pnl = pd.to_numeric(trades["REALIZED PNL"], errors="coerce").sum()
    total_prem= pd.to_numeric(trades["PREMIUM / CREDIT"], errors="coerce").sum() * 100  # rough total credits

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("OPEN TRADES",    open_ct)
    k2.metric("CLOSED TRADES",  closed_ct)
    k3.metric("REALIZED P&L",   f"${total_pnl:,.2f}")
    k4.metric("TOTAL PREMIUM COLLECTED (APPROX)", f"${total_prem:,.0f}")

    st.markdown("---")

    # ── Full trade table (editable) ───────────────────────────────────────────
    st.markdown("### ALL TRADES")
    st.caption("You can edit cells directly in the table below.")

    edited = st.data_editor(
        trades,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "STATUS": st.column_config.SelectboxColumn(
                "STATUS",
                options=["OPEN","EXPIRED (FULL PROFIT)","CLOSED EARLY","ASSIGNED / EXERCISED","ROLLED"],
            ),
            "REALIZED PNL": st.column_config.NumberColumn("REALIZED PNL", format="$%.2f"),
            "PREMIUM / CREDIT": st.column_config.NumberColumn("PREMIUM / CREDIT", format="$%.2f"),
            "CASH SECURED": st.column_config.NumberColumn("CASH SECURED", format="$%.0f"),
            "MAX LOSS": st.column_config.NumberColumn("MAX LOSS", format="$%.0f"),
        }
    )
    if not edited.equals(trades):
        st.session_state["trades"] = edited
        st.rerun()

    # ── P&L by strategy ───────────────────────────────────────────────────────
    closed = trades[trades["STATUS"] != "OPEN"].copy()
    if not closed.empty:
        closed["REALIZED PNL"] = pd.to_numeric(closed["REALIZED PNL"], errors="coerce")
        by_strat = closed.groupby("STRATEGY")["REALIZED PNL"].agg(["sum","count"]).reset_index()
        by_strat.columns = ["STRATEGY", "TOTAL PNL", "TRADES"]
        st.markdown("### P&L BY STRATEGY")
        st.dataframe(
            by_strat.style.format({"TOTAL PNL": "${:,.2f}"}),
            use_container_width=True, hide_index=True
        )
else:
    st.info("No trades logged yet. Add your first trade above.")

st.markdown("---")
st.caption("DATA IS SESSION-ONLY — EXPORT CSV BEFORE CLOSING THE BROWSER TO SAVE YOUR TRADES")
