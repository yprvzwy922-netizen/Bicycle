"""
Supabase persistence layer (REST / PostgREST via requests — no extra SDK).

If SUPABASE_URL + SUPABASE_KEY are present in st.secrets, trades, watchlist
and snapshots persist in Postgres and are shared across PCs/sessions.
If not configured, everything falls back to session_state (old behaviour).

Schema: see supabase_schema.sql at the repo root.
"""
import numpy as np
import pandas as pd
import requests
import streamlit as st

# App-side trade columns (single source of truth for the Trade Log / Portfolio)
TRADE_COLUMNS = [
    "ID","DATE OPENED","TICKER","STRATEGY",
    "SHORT STRIKE","LONG STRIKE","EXPIRY","DTE OPEN",
    "CONTRACTS","PREMIUM / CREDIT","CASH SECURED","MAX LOSS",
    "STATUS","DATE CLOSED","CLOSE PRICE","REALIZED PNL","SIGNAL","NOTES"
]

_COL2DB = {
    "ID":"id", "DATE OPENED":"date_opened", "TICKER":"ticker", "STRATEGY":"strategy",
    "SHORT STRIKE":"short_strike", "LONG STRIKE":"long_strike", "EXPIRY":"expiry",
    "DTE OPEN":"dte_open", "CONTRACTS":"contracts", "PREMIUM / CREDIT":"premium",
    "CASH SECURED":"cash_secured", "MAX LOSS":"max_loss", "STATUS":"status",
    "DATE CLOSED":"date_closed", "CLOSE PRICE":"close_price",
    "REALIZED PNL":"realized_pnl", "SIGNAL":"signal", "NOTES":"notes",
}
_DB2COL = {v: k for k, v in _COL2DB.items()}

# ── Connection ────────────────────────────────────────────────────────────────
def _creds():
    try:
        url = str(st.secrets["SUPABASE_URL"]).rstrip("/")
        key = str(st.secrets["SUPABASE_KEY"])
        if url and key:
            return url, key
    except Exception:
        pass
    return None, None

def configured() -> bool:
    url, key = _creds()
    return bool(url and key)

def _rest(method, table, params=None, json=None, prefer=None):
    url, key = _creds()
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    r = requests.request(method, f"{url}/rest/v1/{table}",
                         headers=headers, params=params, json=json, timeout=12)
    r.raise_for_status()
    return r.json() if r.text else None

def _clean(records):
    """NaN/NaT -> None so JSON serialization is valid."""
    out = []
    for rec in records:
        out.append({k: (None if (v is None or (isinstance(v, float) and np.isnan(v))
                                 or v is pd.NaT or str(v) == "nan") else v)
                    for k, v in rec.items()})
    return out

# ── Trades ────────────────────────────────────────────────────────────────────
def load_trades() -> pd.DataFrame:
    rows = _rest("GET", "trades", params={"select": "*", "order": "id"}) or []
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    df = df.rename(columns=_DB2COL)
    for c in TRADE_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[TRADE_COLUMNS]

def replace_trades(df: pd.DataFrame):
    """Upsert every row; delete DB rows whose id is no longer in df."""
    recs = df.rename(columns=_COL2DB)[list(_COL2DB.values())].to_dict("records")
    recs = _clean(recs)
    recs = [r for r in recs if r.get("id") is not None]
    if recs:
        _rest("POST", "trades", json=recs,
              prefer="resolution=merge-duplicates,return=minimal")
    keep = {int(r["id"]) for r in recs}
    existing = _rest("GET", "trades", params={"select": "id"}) or []
    stale = [str(int(r["id"])) for r in existing if int(r["id"]) not in keep]
    if stale:
        _rest("DELETE", "trades", params={"id": f"in.({','.join(stale)})"},
              prefer="return=minimal")

def get_trades_df() -> pd.DataFrame:
    """DB-backed when configured (DB = source of truth), else session_state."""
    if configured():
        try:
            df = load_trades()
            st.session_state["trades"] = df
            return df
        except Exception as e:
            st.warning(f"DB read failed — using session copy. ({e})")
    if "trades" not in st.session_state:
        st.session_state["trades"] = pd.DataFrame(columns=TRADE_COLUMNS)
    return st.session_state["trades"]

def save_trades_df(df: pd.DataFrame):
    st.session_state["trades"] = df
    if configured():
        try:
            replace_trades(df)
        except Exception as e:
            st.error(f"DB write failed — change kept in session only. ({e})")

# ── Watchlist ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def _watchlist_rows():
    return _rest("GET", "watchlist", params={"select": "*", "order": "ticker"}) or []

def load_watchlist():
    try:
        return [{"ticker": r["ticker"], "company": r.get("company") or "",
                 "sector": r.get("sector") or "Technology",
                 "bucket": r.get("bucket") or "Growth",
                 "conviction": r.get("conviction") or 3,
                 "delta_band": r.get("delta_band") or "Income"}
                for r in _watchlist_rows()]
    except Exception:
        return []

def seed_watchlist(items):
    recs = [{"ticker": w["ticker"], "company": w["company"], "sector": w["sector"],
             "bucket": w["bucket"], "conviction": w["conviction"],
             "delta_band": w["delta_band"]} for w in items]
    _rest("POST", "watchlist", json=recs,
          prefer="resolution=merge-duplicates,return=minimal")
    _watchlist_rows.clear()

def upsert_watchlist_item(item: dict):
    _rest("POST", "watchlist", json=[item],
          prefer="resolution=merge-duplicates,return=minimal")
    _watchlist_rows.clear()

def delete_watchlist_item(ticker: str):
    _rest("DELETE", "watchlist", params={"ticker": f"eq.{ticker.upper()}"},
          prefer="return=minimal")
    _watchlist_rows.clear()

# ── Snapshots (written by scripts/daily_snapshot.py) ──────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_portfolio_snapshots() -> pd.DataFrame:
    try:
        rows = _rest("GET", "portfolio_snapshots",
                     params={"select": "*", "order": "snap_date"}) or []
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()
