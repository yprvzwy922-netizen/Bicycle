"""
Trade Log — all strategies, auto-calculated fields, CSV export/import.
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
if db.configured():
    st.caption("STORAGE: SUPABASE (SHARED, PERSISTENT — SAME BOOK ON EVERY PC) | DTE, CASH SECURED, MAX LOSS AUTO-CALCULATED")
else:
    st.caption("STORAGE: SESSION ONLY — EXPORT CSV BEFORE CLOSING | SET SUPABASE SECRETS TO ENABLE SHARED PERSISTENCE")

# ── Store (DB-backed when configured, session otherwise) ──────────────────────
COLUMNS = db.TRADE_COLUMNS
trades: pd.DataFrame = db.get_trades_df()

# ── Import / Export ───────────────────────────────────────────────────────────
c_imp, c_exp, _ = st.columns([2, 2, 6])
with c_imp:
    uploaded = st.file_uploader("IMPORT CSV", type="csv", label_visibility="collapsed")
    if uploaded:
        try:
            loaded = pd.read_csv(uploaded)
            for c in COLUMNS:
                if c not in loaded.columns:
                    loaded[c] = None
            loaded = loaded[COLUMNS]
            # Import key changes each upload so the same file isn't re-imported every rerun
            imp_key = f"{uploaded.name}_{len(loaded)}"
            if st.session_state.get("last_import") != imp_key:
                merged = pd.concat([trades, loaded], ignore_index=True)
                merged = merged.drop_duplicates(subset=["ID"], keep="last")
                db.save_trades_df(merged)
                st.session_state["last_import"] = imp_key
                st.success(f"Imported {len(loaded)} trades (merged by ID).")
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
    "Short Put":                  {"legs":"single","type":"put",  "short":True},
    "Cash-Secured Put (Wheel)":   {"legs":"single","type":"put",  "short":True},
    "Bull Put Spread":            {"legs":"spread","type":"put",  "short":True},
    "Covered Call":               {"legs":"single","type":"call", "short":True},
    "Bear Call Spread":           {"legs":"spread","type":"call", "short":True},
    "Long Put (Hedge)":           {"legs":"single","type":"put",  "short":False},
    "Long Call":                  {"legs":"single","type":"call", "short":False},
    # Stock positions: CONTRACTS = SHARES, PREMIUM / CREDIT = entry price/share,
    # no expiry, multiplier 1 (not 100)
    "Long Stock":                 {"legs":"stock", "type":"stock","short":False},
}

def strat_mult(strategy: str) -> int:
    """P&L multiplier: 1 for stock (per share), 100 for option contracts."""
    return 1 if STRATEGIES.get(str(strategy), {}).get("legs") == "stock" else 100

STRAT_NAMES = list(STRATEGIES.keys())

# ── Auto-calc preview (outside form so it updates live) ───────────────────────
st.markdown("### NEW TRADE")

# Use session keys so values persist across reruns while filling the form
def ss(key, default): return st.session_state.setdefault(f"nt_{key}", default)

cc1, cc2, cc3, cc4 = st.columns(4)
nt_date     = cc1.date_input("DATE OPENED", datetime.date.today(), key="nt_date")
nt_ticker   = cc2.text_input("TICKER", key="nt_ticker").upper().strip()
nt_strategy = cc3.selectbox("STRATEGY", STRAT_NAMES, key="nt_strategy")
strat_def   = STRATEGIES[nt_strategy]
is_spread   = strat_def["legs"] == "spread"
is_stock    = strat_def["legs"] == "stock"
nt_contracts= cc4.number_input("SHARES" if is_stock else "CONTRACTS",
                               min_value=1, value=100 if is_stock else 1, key="nt_contracts")

sc1, sc2, sc3 = st.columns(3)
nt_short_strike = sc1.number_input(
    "SHORT STRIKE (sell leg)" + (" — N/A FOR STOCK" if is_stock else ""),
    min_value=0.0, step=0.50, key="nt_short_strike", disabled=is_stock)
nt_long_strike  = sc2.number_input(
    "LONG STRIKE (buy leg)" + (" — SPREADS ONLY" if is_spread else " — not needed"),
    min_value=0.0, step=0.50, key="nt_long_strike",
    disabled=not is_spread,
    help="Only for spreads — the strike you buy as protection"
)
nt_expiry = sc3.date_input("EXPIRY DATE" + (" — N/A FOR STOCK" if is_stock else ""),
                           datetime.date.today() + datetime.timedelta(days=35),
                           key="nt_expiry", disabled=is_stock)

pc1, pc1b, pc2 = st.columns(3)
nt_premium = pc1.number_input(
    "ENTRY PRICE PER SHARE" if is_stock else "PREMIUM / NET CREDIT (per share)",
    min_value=0.0, step=0.01, key="nt_premium",
    help="Stock: your purchase price per share." if is_stock else
         "For short options: credit received per share. For spreads: net credit = sell leg − buy leg.")
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
nt_dte = None if is_stock else max((nt_expiry - datetime.date.today()).days, 0)

if is_stock:
    # Long stock: cost basis = price x shares; worst case stock -> $0
    nt_cash_secured = nt_premium * nt_contracts
    nt_max_loss = nt_cash_secured
    cash_note = f"Entry ${nt_premium:.2f} × {nt_contracts} shares = ${nt_cash_secured:,.0f}"
    loss_note = f"Stock → $0 = ${nt_max_loss:,.0f}"

elif strat_def["type"] == "put" and strat_def["short"] and not is_spread:
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
pc3.metric("DTE (AUTO)", "—" if nt_dte is None else nt_dte, help="Expiry date − today (N/A for stock)")
pc4.metric("CASH DEPLOYED (AUTO)", f"${nt_cash_secured:,.0f}", help=cash_note)
pc5.metric("MAX LOSS (AUTO)", f"${nt_max_loss:,.0f}", help=loss_note)
if is_stock:
    pc6.metric("COST BASIS ($)", f"${nt_premium*nt_contracts:,.0f}",
               help="Entry price × shares")
else:
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
            "SHORT STRIKE":     nt_short_strike if nt_short_strike > 0 and not is_stock else None,
            "LONG STRIKE":      nt_long_strike  if is_spread and nt_long_strike > 0 else None,
            "EXPIRY":           None if is_stock else nt_expiry.isoformat(),
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
        db.save_trades_df(pd.concat([trades, pd.DataFrame([new_row])], ignore_index=True))
        if is_stock:
            st.success(f"Added: {nt_strategy} on {nt_ticker} | {nt_contracts} shares @ ${nt_premium:.2f} | Cost ${nt_premium*nt_contracts:,.0f}")
        else:
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

    # Strategy facts used by both preview and the close action
    def _close_facts(row):
        strat    = str(row["STRATEGY"])
        sdef     = STRATEGIES.get(strat, {})
        is_short = sdef.get("short", True)
        mult     = strat_mult(strat)
        prem     = float(row["PREMIUM / CREDIT"] or 0)
        ctrs     = int(row["CONTRACTS"])
        strike   = float(row["SHORT STRIKE"]) if pd.notna(row["SHORT STRIKE"]) else 0.0
        assigned = close_status == "ASSIGNED / EXERCISED"
        # Single-leg short put assigned -> you are put the shares at the strike
        put_assigned = (assigned and is_short and sdef.get("type") == "put"
                        and sdef.get("legs") == "single")
        cc_assigned  = assigned and strat == "Covered Call"
        # On assignment the option premium is kept in full (no buyback)
        if assigned and is_short:
            realized = prem * mult * ctrs
        elif is_short:
            realized = (prem - close_price) * mult * ctrs
        else:
            realized = (close_price - prem) * mult * ctrs
        return dict(strat=strat, is_short=is_short, mult=mult, prem=prem, ctrs=ctrs,
                    strike=strike, put_assigned=put_assigned, cc_assigned=cc_assigned,
                    realized=realized)

    if close_id:
        row = trades[trades["ID"] == close_id].iloc[0]
        f   = _close_facts(row)
        max_l      = float(row["MAX LOSS"]) if pd.notna(row["MAX LOSS"]) and row["MAX LOSS"] else 0
        return_pct = f["realized"] / max_l if max_l else 0
        st.info(f"REALIZED P&L: **${f['realized']:,.2f}**  |  Return on capital: **{return_pct:.1%}**")
        if f["put_assigned"] and f["strike"] > 0:
            eff = f["strike"] - f["prem"]
            st.warning(f"ASSIGNMENT → will create LONG STOCK: **{f['ctrs']*100} shares of "
                       f"{row['TICKER']} @ ${f['strike']:.2f}** (effective basis ${eff:.2f} after premium). "
                       f"Next step per manual: sell covered calls.")
        elif f["cc_assigned"]:
            st.warning("COVERED CALL ASSIGNED → your shares are CALLED AWAY. "
                       "Close/trim the matching LONG STOCK position manually in the table below.")

    if st.button("CLOSE TRADE", type="primary"):
        row = trades[trades["ID"] == close_id].iloc[0]
        f   = _close_facts(row)
        idx = trades[trades["ID"] == close_id].index[0]
        trades.at[idx, "STATUS"]      = close_status
        trades.at[idx, "DATE CLOSED"] = close_date.isoformat()
        trades.at[idx, "CLOSE PRICE"] = close_price
        trades.at[idx, "REALIZED PNL"]= round(f["realized"], 2)

        new_frame = trades
        msg = f"Trade #{close_id} closed. P&L: ${f['realized']:,.2f}"

        # Short put assigned -> auto-create the Long Stock leg of the wheel
        if f["put_assigned"] and f["strike"] > 0:
            ids = pd.to_numeric(trades["ID"], errors="coerce").dropna()
            stock_id = int(ids.max()) + 1 if not ids.empty else 1
            shares   = f["ctrs"] * 100
            stock_row = {c: None for c in COLUMNS}
            stock_row.update({
                "ID": stock_id, "DATE OPENED": close_date.isoformat(),
                "TICKER": row["TICKER"], "STRATEGY": "Long Stock",
                "CONTRACTS": shares, "PREMIUM / CREDIT": f["strike"],
                "CASH SECURED": round(f["strike"] * shares, 2),
                "MAX LOSS": round(f["strike"] * shares, 2),
                "STATUS": "OPEN", "SIGNAL": row.get("SIGNAL"),
                "NOTES": f"Assigned from put #{close_id} @ ${f['strike']:.2f}",
            })
            new_frame = pd.concat([trades, pd.DataFrame([stock_row])], ignore_index=True)
            msg += f"  →  Created LONG STOCK: {shares} sh {row['TICKER']} @ ${f['strike']:.2f}"

        db.save_trades_df(new_frame)
        st.success(msg)
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
    # Option credits only — for Long Stock the premium column is an entry price
    opt_rows   = trades[trades["STRATEGY"] != "Long Stock"]
    total_cred = (pd.to_numeric(opt_rows["PREMIUM / CREDIT"], errors="coerce") *
                  pd.to_numeric(opt_rows["CONTRACTS"], errors="coerce")).sum() * 100

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
        # Rows added in the editor get the next free ID before persisting
        if edited["ID"].isna().any():
            ids = pd.to_numeric(edited["ID"], errors="coerce")
            nxt = int(ids.max()) + 1 if ids.notna().any() else 1
            for i in edited.index[ids.isna()]:
                edited.at[i, "ID"] = nxt
                nxt += 1
        db.save_trades_df(edited)
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

    # ── Income chart — realized premium vs the plan ───────────────────────────
    if not closed.empty and closed["DATE CLOSED"].notna().any():
        inc = closed[closed["DATE CLOSED"].notna()].copy()
        inc["MONTH"] = pd.to_datetime(inc["DATE CLOSED"], errors="coerce").dt.to_period("M").astype(str)
        monthly = inc.groupby("MONTH")["REALIZED PNL"].sum().reset_index()
        monthly["CUMULATIVE"] = monthly["REALIZED PNL"].cumsum()

        st.markdown("### REALIZED INCOME")
        fig = go.Figure()
        fig.add_bar(x=monthly["MONTH"], y=monthly["REALIZED PNL"], name="MONTHLY P&L",
                    marker_color="#00c8ff")
        fig.add_scatter(x=monthly["MONTH"], y=monthly["CUMULATIVE"], name="CUMULATIVE",
                        mode="lines+markers", line=dict(color="#00e676", width=2))
        # Manual plan: 30% on $1M = ~$25k/month glidepath
        fig.add_scatter(x=monthly["MONTH"], y=[25000*(i+1) for i in range(len(monthly))],
                        name="PLAN (30% / $25K MO)", mode="lines",
                        line=dict(color="#ff9900", width=1, dash="dot"))
        fig.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            legend=dict(orientation="h", y=1.1),
            margin=dict(l=40, r=20, t=30, b=40), height=360,
            xaxis=dict(gridcolor="#1e1e1e"), yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trades yet. Add your first trade above.")

st.markdown("---")
if db.configured():
    st.caption("STORAGE: SUPABASE — TRADES SHARED ACROSS ALL PCS AND SESSIONS")
else:
    st.caption("SESSION ONLY — EXPORT CSV BEFORE CLOSING BROWSER")
