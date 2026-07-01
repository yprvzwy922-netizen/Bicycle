"""
Order Ticket — collect the options you picked this session and turn them into a
broker-ready message:  sell 50 cts NUAI US 07/17/26 P5 at 0.60
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import streamlit as st
import bbg_style
import ticket

st.set_page_config(page_title="Order Ticket", layout="wide")
bbg_style.inject()

if not st.session_state.get("authenticated"):
    st.warning("Please log in.")
    if st.button("HOME"): st.switch_page("app.py")
    st.stop()

c1, c2, _ = st.columns([1, 2, 7])
with c1:
    if st.button("HOME"): st.switch_page("app.py")
with c2:
    if st.button("← OPTION FINDER"): st.switch_page("pages/4_Option_Finder.py")

st.title("ORDER TICKET")
st.caption("PICK STRIKES IN THE OPTION FINDER → THEY LAND HERE → COPY THE MESSAGE TO YOUR TRADER")

items = ticket.get_ticket()

if not items:
    st.info("Ticket is empty. Open the Option Finder, choose a strike, set contracts, and click ＋ ADD.")
    if st.button("GO TO OPTION FINDER", type="primary"):
        st.switch_page("pages/4_Option_Finder.py")
    st.stop()

# ── Editable line items ───────────────────────────────────────────────────────
st.markdown("### ITEMS")
df = pd.DataFrame(items)
df_disp = df.copy()
df_disp["LINE"] = [ticket.format_line(it) for it in items]
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
# Push edits (action / price / contracts) back into the ticket
for i, it in enumerate(items):
    it["action"]    = str(edited.iloc[i]["action"])
    it["price"]     = float(edited.iloc[i]["price"])
    it["contracts"] = int(edited.iloc[i]["contracts"])

cdel1, cdel2, _ = st.columns([2, 2, 6])
rm = cdel1.selectbox("REMOVE LINE #", ["—"] + [f"{i+1}" for i in range(len(items))])
if cdel2.button("REMOVE") and rm != "—":
    ticket.remove_from_ticket(int(rm) - 1)
    st.rerun()

st.markdown("---")

# ── Message ───────────────────────────────────────────────────────────────────
st.markdown("### MESSAGE TO TRADER")
mc1, mc2 = st.columns([2, 8])
account = mc1.text_input("ACCOUNT (optional)", key="ticket_account")

# Totals
total_contracts = sum(it["contracts"] for it in items)
total_credit = sum(it["contracts"] * it["price"] * 100 for it in items
                   if str(it["action"]).startswith("sell"))
k1, k2, k3 = st.columns(3)
k1.metric("LINES", len(items))
k2.metric("TOTAL CONTRACTS", total_contracts)
k3.metric("EST. CREDIT", f"${total_credit:,.0f}")

msg = ticket.format_message(items, account)
st.code(msg, language=None)
st.caption("Select the text above and copy, or use the download button.")

dc1, dc2, _ = st.columns([2, 2, 6])
dc1.download_button("DOWNLOAD .TXT", msg.encode(), "order_ticket.txt", "text/plain",
                    use_container_width=True, type="primary")
if dc2.button("CLEAR TICKET", use_container_width=True):
    ticket.clear_ticket()
    st.rerun()
