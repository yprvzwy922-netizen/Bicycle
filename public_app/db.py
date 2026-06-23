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
    "STATUS","DATE CLOSED","CLOSE PRICE","REALIZED PNL","SIGNAL",
    "RECOMMENDED BY","CONSENSUS","NOTES"
]

_COL2DB = {
    "ID":"id", "DATE OPENED":"date_opened", "TICKER":"ticker", "STRATEGY":"strategy",
    "SHORT STRIKE":"short_strike", "LONG STRIKE":"long_strike", "EXPIRY":"expiry",
    "DTE OPEN":"dte_open", "CONTRACTS":"contracts", "PREMIUM / CREDIT":"premium",
    "CASH SECURED":"cash_secured", "MAX LOSS":"max_loss", "STATUS":"status",
    "DATE CLOSED":"date_closed", "CLOSE PRICE":"close_price",
    "REALIZED PNL":"realized_pnl", "SIGNAL":"signal",
    "RECOMMENDED BY":"recommended_by", "CONSENSUS":"consensus", "NOTES":"notes",
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
    if not r.ok:
        # Surface Supabase's actual message (RLS, missing column, bad key, etc.)
        raise RuntimeError(f"{method} {table} -> HTTP {r.status_code}: {r.text[:400]}")
    return r.json() if r.text else None

def _clean(records):
    """Make rows JSON-serializable for requests: numpy scalars -> Python natives,
    NaN/NaT/'nan' -> None. (requests' JSON encoder can't handle numpy int64.)"""
    def fix(v):
        if v is None or v is pd.NaT:
            return None
        if isinstance(v, np.generic):          # numpy scalar -> python scalar
            v = v.item()
        if isinstance(v, float) and np.isnan(v):
            return None
        if isinstance(v, str) and v.strip().lower() == "nan":
            return None
        return v
    return [{k: fix(v) for k, v in rec.items()} for rec in records]

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

def save_trades_df(df: pd.DataFrame) -> bool:
    """Returns True if persisted (DB write ok, or session-only mode)."""
    st.session_state["trades"] = df
    if configured():
        try:
            replace_trades(df)
            return True
        except Exception as e:
            st.error(f"DB write failed — change kept in session only. ({e})")
            return False
    return True

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

def sync_missing_watchlist(defaults) -> int:
    """Add default names not already in the watchlist (non-destructive — never
    overwrites your existing rows). Returns how many were added."""
    have = {w["ticker"] for w in load_watchlist()} if configured() else \
           set(st.session_state.get("watchlist", {}).keys())
    missing = [w for w in defaults if w["ticker"] not in have]
    if not missing:
        return 0
    if configured():
        _rest("POST", "watchlist", json=[{
            "ticker": w["ticker"], "company": w["company"], "sector": w["sector"],
            "bucket": w["bucket"], "conviction": w["conviction"],
            "delta_band": w["delta_band"]} for w in missing],
            prefer="resolution=merge-duplicates,return=minimal")
        _watchlist_rows.clear()
    else:
        wl = st.session_state.setdefault("watchlist", {})
        for w in missing:
            wl[w["ticker"]] = w
    return len(missing)

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

# ── Fund: investors / contributions / fund history ────────────────────────────
CONTRIB_COLUMNS = ["id", "investor", "date", "amount", "units_issued", "nav_per_unit"]

def load_investors() -> list:
    if configured():
        try:
            rows = _rest("GET", "investors", params={"select": "*", "order": "name"}) or []
            return [r["name"] for r in rows]
        except Exception:
            pass
    return list(st.session_state.get("investors", []))

def add_investor(name: str):
    name = name.strip()
    if not name:
        return
    if configured():
        try:
            _rest("POST", "investors", json=[{"name": name}],
                  prefer="resolution=merge-duplicates,return=minimal")
            return
        except Exception as e:
            st.warning(f"DB write failed — session only. ({e})")
    st.session_state.setdefault("investors", [])
    if name not in st.session_state["investors"]:
        st.session_state["investors"].append(name)

def load_contributions() -> pd.DataFrame:
    if configured():
        try:
            rows = _rest("GET", "contributions",
                         params={"select": "*", "order": "id"}) or []
            df = pd.DataFrame(rows)
            return df if not df.empty else pd.DataFrame(columns=CONTRIB_COLUMNS)
        except Exception:
            pass
    return st.session_state.get("contributions", pd.DataFrame(columns=CONTRIB_COLUMNS))

def add_contribution(investor, date, amount, units_issued, nav_per_unit):
    cur = load_contributions()
    new_id = (int(pd.to_numeric(cur["id"], errors="coerce").max()) + 1
              if not cur.empty else 1)
    rec = {"id": new_id, "investor": investor, "date": date,
           "amount": float(amount), "units_issued": float(units_issued),
           "nav_per_unit": float(nav_per_unit)}
    if configured():
        try:
            _rest("POST", "contributions", json=[rec], prefer="return=minimal")
            return
        except Exception as e:
            st.warning(f"DB write failed — session only. ({e})")
    st.session_state["contributions"] = pd.concat(
        [cur, pd.DataFrame([rec])], ignore_index=True)

@st.cache_data(ttl=300, show_spinner=False)
def load_fund_snapshots() -> pd.DataFrame:
    try:
        rows = _rest("GET", "fund_snapshots",
                     params={"select": "*", "order": "snap_date"}) or []
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()
