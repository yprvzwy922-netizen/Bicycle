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
    """The trading day to stamp the snapshot with. Uses SPY's last daily bar,
    which handles weekends AND holidays for free. On a trading day this is TODAY
    (even intraday — we capture a current snapshot for today and overwrite it
    later at close), so a run NEVER rewrites a completed past day. Only weekends/
    holidays roll back to the prior session (SPY has no bar for those)."""
    now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
    try:
        h = yf.Ticker("SPY").history(period="7d")
        if not h.empty:
            return h.index[-1].date()
    except Exception:
        pass
    d = now_et.date()
    while d.weekday() >= 5:        # weekend -> roll back to Friday
        d -= datetime.timedelta(days=1)
    return d

TODAY = last_trading_day().isoformat()
TODAY_ET = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
# A snapshot dated before the actual current ET date is a COMPLETED past
# session — never overwrite it. Only the live (current) day may be rewritten
# (intraday -> close). This keeps stored history immutable.
IS_PAST_DAY = TODAY < TODAY_ET
print(f"snapshot date: {TODAY}  (today ET: {TODAY_ET}, past-day lock: {IS_PAST_DAY})")

def already_stored(table):
    try:
        rows = rest("GET", table, params={"select": "snap_date", "snap_date": f"eq.{TODAY}"})
        return bool(rows)
    except Exception:
        return False

def should_skip(table):
    if IS_PAST_DAY and already_stored(table):
        print(f"{table} {TODAY} already stored (completed day) — NOT overwriting")
        return True
    return False

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
        strat = str(t["strategy"])
        prem, ctrs = float(t["premium"] or 0), int(t["contracts"] or 0)
        tkr = t["ticker"]
        # Manual mark (typed from the broker in the app) beats the live feed
        mmark = t.get("manual_mark")
        mmark = float(mmark) if mmark not in (None, "", 0) else None
        # Long Stock: mark vs entry price, per share
        if strat == "Long Stock":
            if mmark and prem > 0:
                unreal += (mmark - prem) * ctrs
                continue
            h = yf.Ticker(tkr).history(period="2d")
            if not h.empty and prem > 0:
                unreal += (float(h["Close"].iloc[-1]) - prem) * ctrs
            continue
        if mmark:
            is_short = strat not in ("Long Put (Hedge)", "Long Call")
            unreal += ((prem - mmark) if is_short else (mmark - prem)) * 100 * ctrs
            continue
        strike, expiry = float(t["short_strike"] or 0), t.get("expiry")
        if not strike or not expiry:
            continue
        opt_type = "put" if "Put" in strat else "call"
        raw = yf.Ticker(tkr).option_chain(expiry)
        chain = raw.puts if opt_type == "put" else raw.calls
        if chain is None or chain.empty:
            continue
        chain = chain.copy()
        chain["dist"] = (chain["strike"] - strike).abs()
        row = chain.loc[chain["dist"].idxmin()]
        # Don't snap to a strike we don't actually hold, and don't mark a
        # contract with no quotes — either would corrupt NAV. Leave it flat.
        if float(row["dist"]) > max(0.015 * strike, 0.50):
            continue
        bid, ask = float(row["bid"]), float(row["ask"])
        if not (bid > 0 and ask > 0):
            continue                               # no reliable quote -> leave flat
        mid = (bid + ask) / 2
        is_short = strat not in ("Long Put (Hedge)", "Long Call")
        unreal += ((prem - mid) if is_short else (mid - prem)) * 100 * ctrs
    except Exception as e:
        print(f"  mark {t.get('ticker')}: {e}")

if not should_skip("portfolio_snapshots"):
    rest("POST", "portfolio_snapshots", json=[{
        "snap_date": TODAY,
        "open_positions": len(open_t),
        "total_credits": round(credits, 2),
        "unreal_pnl": round(unreal, 2),
        "realized_pnl": round(realized, 2),
        "cash_secured": round(cash_sec, 2),
    }], prefer="resolution=merge-duplicates,return=minimal")
    # Public repo -> Actions logs are public. Never print dollar values.
    print(f"portfolio snapshot {TODAY}: open={len(open_t)} — written (values redacted)")

# ── Fund NAV snapshot (unitized) ──────────────────────────────────────────────
if not should_skip("fund_snapshots"):
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
        print(f"fund snapshot {TODAY}: written (values redacted)")
    except Exception as e:
        print(f"fund snapshot skipped: {e}")
