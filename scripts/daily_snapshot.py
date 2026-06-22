"""
Daily snapshot job — run by GitHub Actions after US close (or manually).

Writes to Supabase:
  snapshots            one row per watchlist ticker (spot, 21d realized vol, vol rank)
  portfolio_snapshots  one row per day (open positions, credits, unreal/realized P&L)

Needs env vars: SUPABASE_URL, SUPABASE_KEY.
Self-contained on purpose — no streamlit import (shared.py needs a Streamlit runtime).
"""
import datetime
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")

if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY not set")

HDRS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def rest(method, table, params=None, json=None, prefer=None):
    h = dict(HDRS)
    if prefer:
        h["Prefer"] = prefer
    r = requests.request(method, f"{URL}/rest/v1/{table}",
                         headers=h, params=params, json=json, timeout=20)
    r.raise_for_status()
    return r.json() if r.text else None

def last_trading_day():
    """Most recent COMPLETED US trading session, dated correctly no matter when
    GitHub actually runs the job. Primary method derives it from real market
    data (SPY's last daily bar) — that handles weekends AND holidays for free.
    Calendar fallback (weekends only) if the data fetch fails."""
    now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
    try:
        h = yf.Ticker("SPY").history(period="7d")
        if not h.empty:
            last = h.index[-1].date()
            # If run intraday before close, today's forming bar isn't "complete"
            if last == now_et.date() and now_et.time() < datetime.time(16, 0) and len(h) > 1:
                last = h.index[-2].date()
            return last
    except Exception:
        pass
    d = now_et.date()
    if now_et.weekday() < 5 and now_et.time() < datetime.time(16, 0):
        d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d

TODAY = last_trading_day().isoformat()
print(f"snapshot date (last trading day, ET): {TODAY}")

# ── Per-ticker snapshots ──────────────────────────────────────────────────────
wl = rest("GET", "watchlist", params={"select": "ticker"}) or []
tickers = sorted({w["ticker"] for w in wl})
print(f"watchlist: {len(tickers)} tickers")

ticker_rows = []
for tkr in tickers:
    try:
        t = yf.Ticker(tkr)
        hist = t.history(period="1y")
        if hist.empty:
            continue
        spot = float(hist["Close"].iloc[-1])
        ret = hist["Close"].pct_change().dropna()
        rv = (ret.rolling(21).std() * np.sqrt(252)).dropna()
        rv21 = float(rv.iloc[-1]) if len(rv) else None
        rv_rank = (float(np.clip((rv.iloc[-1] - rv.min()) / (rv.max() - rv.min()), 0, 1))
                   if len(rv) > 10 and rv.max() > rv.min() else None)
        ticker_rows.append({"snap_date": TODAY, "ticker": tkr, "spot": round(spot, 4),
                            "rv21": rv21, "rv_rank": rv_rank})
    except Exception as e:
        print(f"  {tkr}: {e}")

if ticker_rows:
    rest("POST", "snapshots", json=ticker_rows,
         prefer="resolution=merge-duplicates,return=minimal")
    print(f"snapshots written: {len(ticker_rows)}")

# ── Portfolio snapshot ────────────────────────────────────────────────────────
trades = rest("GET", "trades", params={"select": "*"}) or []
open_t = [t for t in trades if t.get("status") == "OPEN"]

realized = sum(float(t["realized_pnl"]) for t in trades if t.get("realized_pnl") is not None)
credits  = sum(float(t["premium"] or 0) * 100 * int(t["contracts"] or 0) for t in trades)
cash_sec = sum(float(t["cash_secured"] or 0) for t in open_t)

unreal = 0.0
for t in open_t:
    try:
        strike, expiry = float(t["short_strike"] or 0), t.get("expiry")
        prem, ctrs = float(t["premium"] or 0), int(t["contracts"] or 0)
        if not strike or not expiry:
            continue
        opt_type = "put" if "Put" in str(t["strategy"]) else "call"
        raw = yf.Ticker(t["ticker"]).option_chain(expiry)
        chain = raw.puts if opt_type == "put" else raw.calls
        row = chain.iloc[(chain["strike"] - strike).abs().idxmin()]
        mid = float((row["bid"] + row["ask"]) / 2)
        is_short = str(t["strategy"]) not in ("Long Put (Hedge)", "Long Call")
        unreal += ((prem - mid) if is_short else (mid - prem)) * 100 * ctrs
    except Exception as e:
        print(f"  mark {t.get('ticker')}: {e}")

rest("POST", "portfolio_snapshots", json=[{
    "snap_date": TODAY,
    "open_positions": len(open_t),
    "total_credits": round(credits, 2),
    "unreal_pnl": round(unreal, 2),
    "realized_pnl": round(realized, 2),
    "cash_secured": round(cash_sec, 2),
}], prefer="resolution=merge-duplicates,return=minimal")

print(f"portfolio snapshot {TODAY}: open={len(open_t)} unreal=${unreal:,.0f} realized=${realized:,.0f}")

# ── Fund NAV snapshot (unitized) ──────────────────────────────────────────────
try:
    contribs = rest("GET", "contributions", params={"select": "*"}) or []
    contributed = sum(float(c["amount"] or 0) for c in contribs)
    units       = sum(float(c["units_issued"] or 0) for c in contribs)
    nav         = contributed + realized + unreal
    nav_per_unit = (nav / units) if units > 0 else 100.0
    rest("POST", "fund_snapshots", json=[{
        "snap_date": TODAY,
        "nav": round(nav, 2),
        "units": round(units, 4),
        "nav_per_unit": round(nav_per_unit, 4),
        "contributed": round(contributed, 2),
        "realized_pnl": round(realized, 2),
        "unreal_pnl": round(unreal, 2),
    }], prefer="resolution=merge-duplicates,return=minimal")
    print(f"fund snapshot {TODAY}: NAV=${nav:,.0f} units={units:,.2f} nav/unit=${nav_per_unit:,.2f}")
except Exception as e:
    print(f"fund snapshot skipped: {e}")
