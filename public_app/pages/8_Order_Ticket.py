"""
Order Ticket — collect the options you picked this session and turn them into a
broker-ready message. Single legs:
    • sell to open 50 cts NUAI US 07/17/26 P5 at 0.60
Rolls (one net-credit spread block each):
    Account L Roll
    DGXX US buy to close 41 cts 07/17/26 P6
    DGXX US sell to open 41 cts 08/21/26 P6
    at 0.40 net credit
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import streamlit as st
import bbg_style
import ticket

bbg_style.inject()

c1, c2, c3, _ = st.columns([1, 2, 2, 5])
with c1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")
with c2:
    if st.button("← OPTION FINDER"): st.switch_page("pages/4_Option_Finder.py")
with c3:
    if st.button("← ROLL FINDER"): st.switch_page("pages/9_Roll_Finder.py")

st.title("ORDER TICKET")
st.caption("PICK STRIKES IN THE OPTION / ROLL FINDER → THEY LAND HERE → COPY THE MESSAGE TO YOUR TRADER")

items   = ticket.get_ticket()
singles = [it for it in items if it.get("kind", "single") == "single"]
rolls   = [it for it in items if it.get("kind") == "roll"]

if not items:
    st.info("Ticket is empty. Add strikes from the Option Finder, or rolls from the Roll Finder.")
    if st.button("GO TO OPTION FINDER", type="primary"):
        st.switch_page("pages/4_Option_Finder.py")
    st.stop()

# ── Single-leg orders ─────────────────────────────────────────────────────────
if singles:
    st.markdown("### SINGLE-LEG ORDERS")
    df_disp = pd.DataFrame(singles)
    df_disp["LINE"] = [ticket.format_line(it) for it in singles]
    edited = st.data_editor(
        df_disp[["action", "ticker", "expiry", "type", "strike", "price", "contracts", "LINE"]],
        use_container_width=True, hide_index=True, num_rows="fixed",
        disabled=["ticker", "expiry", "type", "strike", "LINE"],
        column_config={
            "action":    st.column_config.SelectboxColumn(
                "ACTION", options=["sell to open", "buy to close", "buy to open", "sell to close"]),
            "price":     st.column_config.NumberColumn("PRICE", format="%.2f"),
            "contracts": st.column_config.NumberColumn("CTS", min_value=1, step=1),
            "LINE":      st.column_config.TextColumn("PREVIEW", width="large"),
        })
    for i, it in enumerate(singles):
        it["action"]    = str(edited.iloc[i]["action"])
        it["price"]     = float(edited.iloc[i]["price"])
        it["contracts"] = int(edited.iloc[i]["contracts"])

# ── Rolls ─────────────────────────────────────────────────────────────────────
if rolls:
    st.markdown("### ROLLS")
    for k, r in enumerate(rolls):
        rc1, rc2, rc3, rc4 = st.columns([4, 1.3, 1.3, 1])
        with rc1:
            st.code(ticket.format_roll_block(r), language=None)
        r["contracts"]  = int(rc2.number_input("CTS", min_value=1, value=int(r["contracts"]),
                                               step=1, key=f"roll_cts_{k}"))
        r["net_credit"] = float(rc3.number_input("NET CREDIT", min_value=0.0,
                                                 value=float(r["net_credit"]), step=0.05,
                                                 key=f"roll_cr_{k}"))
        rc4.markdown(" "); rc4.markdown(" ")
        if rc4.button("REMOVE", key=f"roll_rm_{k}", use_container_width=True):
            ticket.get_ticket().remove(r)
            st.rerun()

# Remove a single-leg line
if singles:
    cdel1, cdel2, _ = st.columns([3, 2, 5])
    rm = cdel1.selectbox("REMOVE SINGLE-LEG LINE",
                         ["—"] + [ticket.format_line(it) for it in singles])
    if cdel2.button("REMOVE LINE") and rm != "—":
        for it in singles:
            if ticket.format_line(it) == rm:
                ticket.get_ticket().remove(it)
                break
        st.rerun()

st.markdown("---")

# ── Message ───────────────────────────────────────────────────────────────────
st.markdown("### MESSAGE TO TRADER")
mc1, mc2 = st.columns([2, 8])
account = mc1.text_input("ACCOUNT (optional)", key="ticket_account")

total_contracts = sum(it["contracts"] for it in items)
total_credit  = sum(it["contracts"] * it["price"] * 100 for it in singles
                    if str(it["action"]).startswith("sell"))
total_credit += sum(r["contracts"] * r["net_credit"] * 100 for r in rolls)

k1, k2, k3, k4 = st.columns(4)
k1.metric("LINES", len(singles))
k2.metric("ROLLS", len(rolls))
k3.metric("TOTAL CONTRACTS", total_contracts)
k4.metric("EST. CREDIT", f"${total_credit:,.0f}",
          help="Sell-side single legs + roll net credits")

msg = ticket.format_message(items, account)
st.code(msg, language=None)
st.caption("Select the text above and copy, or use the download button.")

dc1, dc2, _ = st.columns([2, 2, 6])
dc1.download_button("DOWNLOAD .TXT", msg.encode(), "order_ticket.txt", "text/plain",
                    use_container_width=True, type="primary")
if dc2.button("CLEAR TICKET", use_container_width=True):
    ticket.clear_ticket()
    st.rerun()
