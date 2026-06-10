"""
Trade Log — all strategies, auto-calculated fields, CSV export/import.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
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
st.caption("DTE, CASH SECURED, AND MAX LOSS ARE AUTO-CALCULATED FROM YOUR INPUTS | EXPORT CSV TO SAVE BETWEEN SESSIONS")

# ── Session store ─────────────────────────────────────────────────────────────
COLUMNS = [
    "ID","DATE OPENED","TICKER","STRATEGY",
    "SHORT STRIKE","LONG STRIKE","EXPIRY","DTE OPEN",
    "CONTRACTS","PREMIUM / CREDIT","CASH SECURED","MAX LOSS",
    "STATUS","DATE CLOSED","CLOSE PRICE","REALIZED PNL","SIGNAL","NOTES"
]

if "trades" not in st.session_state:
    st.session_state["trades"] = pd.DataFrame(columns=COLUMNS)

trades: pd.DataFrame = st.session_state["trades"]

# ── Import / Export ───────────────────────────────────────────────────────────
c_imp, c_exp, _ = st.columns([2, 2, 6])
with c_imp:
    uploaded = st.file_uploader("IMPORT CSV", type="csv", label_visibility="collapsed")
    if uploaded:
        try:
            loaded = pd.read_csv(uploaded)
            st.session_state["trades"] = loaded
            trades = loaded
            st.success(f"Loaded {len(loaded)} trades.")
            st.rerun()
        except Exception as e:
            st.error(f"Failed: {e}")
with c_exp:
    st.markdown(" ")
    if not trades.empty:
        st.download_button("EXPORT CSV", trades.to_csv(index=False).encode(),
                           f"trades_{datetime.date.today()}.csv", "text/csv",
                           use_container_width=True, type="primary")

st.markdown("---")

# ── Strategy definitions (drives auto-calc logic) ─────────────────────────────
STRATEGIES = {
    "Short Put":                  {"legs":"single","type":"put", "short":True},
    "Cash-Secured Put (Wheel)":   {"legs":"single","type":"put", "short":True},
    "Bull Put Spread":            {"legs":"spread","type":"put", "short":True},
    "Covered Call":               {"legs":"single","type":"call","short":True},
    "Bear Call Spread":           {"legs":"spread","type":"call","short":True},
    "Long Put (Hedge)":           {"legs":"single","type":"put", "short":False},
    "Long Call":                  {"legs":"single","type":"call","short":False},
}

STRAT_NAMES = list(STRATEGIES.keys())

# ── Auto-calc preview (outside form so it updates live) ───────────────────────
st.markdown("### NEW TRADE")

# Use session keys so values persist across reruns while filling the form
def ss(key, default): return st.session_state.setdefault(f"nt_{key}", default)

cc1, cc2, cc3, cc4 = st.columns(4)
nt_date     = cc1.date_input("DATE OPENED", datetime.date.today(), key="nt_date")
nt_ticker   = cc2.text_input("TICKER", key="nt_ticker").upper().strip()
nt_strategy = cc3.selectbox("STRATEGY", STRAT_NAMES, key="nt_strategy")
nt_contracts= cc4.number_input("CONTRACTS", min_value=1, value=1, key="nt_contracts")

sc1, sc2, sc3 = st.columns(3)
strat_def = STRATEGIES[nt_strategy]
is_spread = strat_def["legs"] == "spread"

nt_short_strike = sc1.number_input("SHORT STRIKE (sell leg)", min_value=0.0, step=0.50, key="nt_short_strike")
nt_long_strike  = sc2.number_input(
    "LONG STRIKE (buy leg)" + (" — SPREADS ONLY" if is_spread else " — not needed"),
    min_value=0.0, step=0.50, key="nt_long_strike",
    disabled=not is_spread,
    help="Only for spreads — the strike you buy as protection"
)
nt_expiry = sc3.date_input("EXPIRY DATE", datetime.date.today() + datetime.timedelta(days=35), key="nt_expiry")

pc1, pc1b, pc2 = st.columns(3)
nt_premium = pc1.number_input("PREMIUM / NET CREDIT (per share)", min_value=0.0, step=0.01, key="nt_premium",
                               help="For short options: credit received per share. For spreads: net credit = sell leg − buy leg.")
# Manual: log the Alpha Trend signal that triggered every trade (daily chart)
nt_signal  = pc1b.selectbox("ALPHA TREND SIGNAL (DAILY)", [
    "MACRO GREEN + STRENGTH",
    "BULLISH TURQUOISE 'R' (CONFIRMED)",
    "MACRO GREEN (PLAIN)",
    "DOTS FLIPPED RED (DE-RISKED)",
    "TOPPING 'T' / YELLOW 'R'",
    "MACRO RED",
    "OTHER / NOT SIGNAL-DRIVEN",
], key="nt_signal")
nt_notes   = pc2.text_input("NOTES", key="nt_notes")

# Auto-calculations
nt_dte = max((nt_expiry - datetime.date.today()).days, 0)

if strat_def["type"] == "put" and strat_def["short"] and not is_spread:
    # Short Put / Wheel: cash secured = strike × 100 × contracts
    nt_cash_secured = nt_short_strike * 100 * nt_contracts
    nt_max_loss = nt_cash_secured  # worst case: stock to zero
    cash_note = f"Strike × 100 × contracts = ${nt_cash_secured:,.0f}"
    loss_note = f"Same as cash secured (stock → $0) = ${nt_max_loss:,.0f}"

elif is_spread and nt_long_strike > 0 and nt_short_strike > 0:
    # Spread: max loss = (width - net credit) × 100 × contracts
    spread_width = abs(nt_long_strike - nt_short_strike)
    nt_cash_secured = 0.0
    nt_max_loss = max((spread_width - nt_premium) * 100 * nt_contracts, 0)
    cash_note = "N/A (spread — margin = max loss)"
    loss_note = f"(Width ${spread_width:.2f} − Credit ${nt_premium:.2f}) × 100 × {nt_contracts} = ${nt_max_loss:,.0f}"

elif strat_def["type"] == "call" and strat_def["short"] and not is_spread:
    # Covered Call: no extra cash needed (you own the stock)
    nt_cash_secured = 0.0
    nt_max_loss = 0.0  # capped by stock ownership
    cash_note = "N/A — you own the underlying"
    loss_note = "Capped by stock ownership (opportunity cost only)"

else:
    nt_cash_secured = nt_short_strike * 100 * nt_contracts if nt_short_strike > 0 else 0
    nt_max_loss = nt_premium * 100 * nt_contracts if not strat_def["short"] else nt_cash_secured
    cash_note = f"${nt_cash_secured:,.0f}"
    loss_note = f"${nt_max_loss:,.0f}"

# Preview calculated values
pc3, pc4, pc5, pc6 = st.columns(4)
pc3.metric("DTE (AUTO)", nt_dte, help="Expiry date − today")
pc4.metric("CASH SECURED (AUTO)", f"${nt_cash_secured:,.0f}", help=cash_note)
pc5.metric("MAX LOSS (AUTO)", f"${nt_max_loss:,.0f}", help=loss_note)
pc6.metric("TOTAL CREDIT ($)", f"${nt_premium*100*nt_contracts:,.0f}",
           help="Premium per share × 100 × contracts")

if st.button("ADD TRADE", type="primary", use_container_width=False):
    if not nt_ticker:
        st.error("Enter a ticker.")
    else:
        # Robust next-ID: handles imported CSVs missing/empty/non-numeric ID column
        if not trades.empty and "ID" in trades.columns:
            ids = pd.to_numeric(trades["ID"], errors="coerce").dropna()
            new_id = int(ids.max()) + 1 if not ids.empty else 1
        else:
            new_id = 1
        new_row = {
            "ID":               new_id,
            "DATE OPENED":      nt_date.isoformat(),
            "TICKER":           nt_ticker,
            "STRATEGY":         nt_strategy,
            "SHORT STRIKE":     nt_short_strike if nt_short_strike > 0 else None,
            "LONG STRIKE":      nt_long_strike  if is_spread and nt_long_strike > 0 else None,
            "EXPIRY":           nt_expiry.isoformat(),
            "DTE OPEN":         nt_dte,
            "CONTRACTS":        nt_contracts,
            "PREMIUM / CREDIT": nt_premium,
            "CASH SECURED":     nt_cash_secured if nt_cash_secured > 0 else None,
            "MAX LOSS":         nt_max_loss     if nt_max_loss > 0 else None,
            "STATUS":           "OPEN",
            "DATE CLOSED":      None,
            "CLOSE PRICE":      None,
            "REALIZED PNL":     None,
            "SIGNAL":           nt_signal,
            "NOTES":            nt_notes,
        }
        st.session_state["trades"] = pd.concat(
            [trades, pd.DataFrame([new_row])], ignore_index=True)
        st.success(f"Added: {nt_strategy} on {nt_ticker} | Strike ${nt_short_strike:.2f} | Expiry {nt_expiry} | Credit ${nt_premium*100*nt_contracts:,.0f}")
        st.rerun()

# ── Close a trade ─────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### CLOSE / EXPIRE A TRADE")

trades = st.session_state["trades"]
open_trades = trades[trades["STATUS"] == "OPEN"].copy() if not trades.empty else pd.DataFrame()

if not open_trades.empty:
    cx1, cx2, cx3, cx4 = st.columns(4)
    close_id = cx1.selectbox(
        "SELECT TRADE",
        open_trades["ID"].tolist(),
        format_func=lambda i: f"#{i}  {open_trades[open_trades['ID']==i]['TICKER'].values[0]}  {open_trades[open_trades['ID']==i]['STRATEGY'].values[0]}  {open_trades[open_trades['ID']==i]['EXPIRY'].values[0]}"
    )
    close_status = cx2.selectbox("OUTCOME", [
        "EXPIRED WORTHLESS (MAX PROFIT)",
        "CLOSED EARLY",
        "ASSIGNED / EXERCISED",
        "ROLLED",
        "STOP LOSS HIT",
    ])
    close_price = cx3.number_input("BUYBACK / CLOSE PRICE (per share)", min_value=0.0, step=0.01,
                                   help="For short options: premium to buy back. 0 if expired worthless.")
    close_date  = cx4.date_input("DATE CLOSED", datetime.date.today(), key="close_date")

    if close_id:
        row = trades[trades["ID"] == close_id].iloc[0]
        prem_orig  = float(row["PREMIUM / CREDIT"] or 0)
        ctrs       = int(row["CONTRACTS"])
        is_short   = STRATEGIES.get(str(row["STRATEGY"]), {}).get("short", True)
        realized   = (prem_orig - close_price) * 100 * ctrs if is_short else (close_price - prem_orig) * 100 * ctrs
        max_l      = float(row["MAX LOSS"]) if pd.notna(row["MAX LOSS"]) and row["MAX LOSS"] else 0
        return_pct = realized / max_l if max_l else 0

        st.info(f"REALIZED P&L: **${realized:,.2f}**  |  Return on capital: **{return_pct:.1%}**")

    if st.button("CLOSE TRADE", type="primary"):
        row = trades[trades["ID"] == close_id].iloc[0]
        prem_orig  = float(row["PREMIUM / CREDIT"] or 0)
        ctrs       = int(row["CONTRACTS"])
        is_short   = STRATEGIES.get(str(row["STRATEGY"]), {}).get("short", True)
        realized   = (prem_orig - close_price) * 100 * ctrs if is_short else (close_price - prem_orig) * 100 * ctrs
        idx = trades[trades["ID"] == close_id].index[0]
        trades.at[idx, "STATUS"]      = close_status
        trades.at[idx, "DATE CLOSED"] = close_date.isoformat()
        trades.at[idx, "CLOSE PRICE"] = close_price
        trades.at[idx, "REALIZED PNL"]= round(realized, 2)
        st.session_state["trades"] = trades
        st.success(f"Trade #{close_id} closed. P&L: ${realized:,.2f}")
        st.rerun()
else:
    st.caption("No open trades.")

# ── Summary ───────────────────────────────────────────────────────────────────
st.markdown("---")
trades = st.session_state["trades"]

if not trades.empty:
    open_ct    = (trades["STATUS"] == "OPEN").sum()
    closed_ct  = (trades["STATUS"] != "OPEN").sum()
    total_pnl  = pd.to_numeric(trades["REALIZED PNL"], errors="coerce").sum()
    total_cred = (pd.to_numeric(trades["PREMIUM / CREDIT"], errors="coerce") *
                  pd.to_numeric(trades["CONTRACTS"], errors="coerce")).sum() * 100

    k1,k2,k3,k4 = st.columns(4)
    k1.metric("OPEN",           open_ct)
    k2.metric("CLOSED",         closed_ct)
    k3.metric("REALIZED P&L",   f"${total_pnl:,.2f}")
    k4.metric("TOTAL CREDITS COLLECTED", f"${total_cred:,.0f}")

    st.markdown("---")
    st.markdown("### ALL TRADES")
    st.caption("Edit cells directly. Changes save automatically to this session.")

    edited = st.data_editor(
        trades,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "STATUS": st.column_config.SelectboxColumn("STATUS", options=[
                "OPEN","EXPIRED WORTHLESS (MAX PROFIT)","CLOSED EARLY",
                "ASSIGNED / EXERCISED","ROLLED","STOP LOSS HIT"]),
            "REALIZED PNL":     st.column_config.NumberColumn(format="$%.2f"),
            "PREMIUM / CREDIT": st.column_config.NumberColumn(format="$%.2f"),
            "CASH SECURED":     st.column_config.NumberColumn(format="$%.0f"),
            "MAX LOSS":         st.column_config.NumberColumn(format="$%.0f"),
        }
    )
    if not edited.equals(trades):
        st.session_state["trades"] = edited
        st.rerun()

    # P&L by strategy
    closed = trades[trades["STATUS"] != "OPEN"].copy()
    if not closed.empty:
        closed["REALIZED PNL"] = pd.to_numeric(closed["REALIZED PNL"], errors="coerce")
        by_strat = closed.groupby("STRATEGY")["REALIZED PNL"].agg(["sum","count","mean"]).reset_index()
        by_strat.columns = ["STRATEGY","TOTAL PNL","TRADES","AVG PNL"]
        st.markdown("### P&L BY STRATEGY")
        st.dataframe(
            by_strat.style.format({"TOTAL PNL":"${:,.2f}","AVG PNL":"${:,.2f}"}),
            use_container_width=True, hide_index=True)
else:
    st.info("No trades yet. Add your first trade above.")

st.markdown("---")
st.caption("SESSION ONLY — EXPORT CSV BEFORE CLOSING BROWSER")
