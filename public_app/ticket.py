"""
Order ticket — a session 'cart' of options you want to trade, plus a formatter
that turns it into broker-ready message lines like:
    sell 50 cts NUAI US 07/17/26 P5 at 0.60
"""
import datetime
import streamlit as st


def get_ticket() -> list:
    return st.session_state.setdefault("ticket", [])


def add_to_ticket(action, ticker, expiry, opt_type, strike, price, contracts):
    """opt_type: 'put'/'call' or 'P'/'C'. expiry: 'YYYY-MM-DD'."""
    get_ticket().append({
        "action":    action.lower(),                 # sell / buy
        "ticker":    ticker.upper(),
        "expiry":    expiry,                          # ISO; formatted on render
        "type":      "P" if str(opt_type).lower().startswith("p") else "C",
        "strike":    float(strike),
        "price":     float(price),
        "contracts": int(contracts),
    })


def remove_from_ticket(idx):
    t = get_ticket()
    if 0 <= idx < len(t):
        t.pop(idx)


def clear_ticket():
    st.session_state["ticket"] = []


def _fmt_expiry(iso):
    try:
        return datetime.datetime.strptime(str(iso), "%Y-%m-%d").strftime("%m/%d/%y")
    except Exception:
        return str(iso)


def _fmt_strike(k):
    # 45.0 -> "45", 5.5 -> "5.5"
    return f"{k:g}"


def format_line(item) -> str:
    return (f"{item['action']} {item['contracts']} cts {item['ticker']} US "
            f"{_fmt_expiry(item['expiry'])} {item['type']}{_fmt_strike(item['strike'])} "
            f"at {item['price']:.2f}")


def format_message(items, account: str = "") -> str:
    header = f"Account {account}\n" if account.strip() else ""
    return header + "\n".join("• " + format_line(it) for it in items)
