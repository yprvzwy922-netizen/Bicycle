"""
Position alerts — runs in the daily GitHub Action (after the snapshot).

Checks every OPEN trade and emails you when one needs attention:
  • PUT TESTED        — spot below your short-put strike (assignment risk)
  • MANAGE-BY DATE    — 1M trade at <=21 DTE, 3M at <=45 DTE (manual §5.1)
  • NEAR EXPIRY ITM   — <=3 DTE and in-the-money
  • PROFIT TARGET     — option mid <= 50% of premium received (take profit)

Email via SMTP. Set these env vars (GitHub Action secrets):
  SUPABASE_URL, SUPABASE_KEY            (read trades)
  ALERT_EMAIL_FROM, ALERT_EMAIL_TO      (addresses)
  ALERT_SMTP_HOST (default smtp.gmail.com), ALERT_SMTP_PORT (default 587)
  ALERT_SMTP_USER, ALERT_SMTP_PASS      (Gmail: an App Password, not your login)
If SMTP vars are missing it just prints the alerts (still useful in the log).
"""
import datetime
import os
import smtplib
import ssl
from email.mime.text import MIMEText

import requests
import yfinance as yf

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("SUPABASE_URL / SUPABASE_KEY not set")

HDRS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
TODAY = datetime.date.today()


def trades():
    r = requests.get(f"{URL}/rest/v1/trades", headers=HDRS,
                     params={"select": "*", "status": "eq.OPEN"}, timeout=20)
    r.raise_for_status()
    return r.json() or []


def spot(tkr):
    try:
        h = yf.Ticker(tkr).history(period="2d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception:
        return None


def opt_mid(tkr, strike, expiry, kind):
    try:
        raw = yf.Ticker(tkr).option_chain(expiry)
        chain = raw.puts if kind == "put" else raw.calls
        row = chain.iloc[(chain["strike"] - strike).abs().idxmin()]
        return float((row["bid"] + row["ask"]) / 2)
    except Exception:
        return None


def check():
    alerts = []
    for t in trades():
        strat = str(t.get("strategy", ""))
        if strat == "Long Stock":
            continue
        tkr = t["ticker"]
        strike = float(t.get("short_strike") or 0)
        expiry = t.get("expiry")
        if not strike or not expiry:
            continue
        kind = "put" if "Put" in strat else "call"
        try:
            dte = (datetime.datetime.strptime(expiry, "%Y-%m-%d").date() - TODAY).days
        except Exception:
            continue
        dte_open = int(t.get("dte_open") or 35)
        manage_at = 45 if dte_open > 60 else 21
        s = spot(tkr)
        prem = float(t.get("premium") or 0)

        if s is not None and kind == "put" and s < strike:
            alerts.append(f"PUT TESTED  {tkr} ${strike:g}P  spot ${s:.2f} below strike ({dte} DTE)")
        if s is not None and kind == "call" and s > strike:
            alerts.append(f"CALL TESTED {tkr} ${strike:g}C  spot ${s:.2f} above strike ({dte} DTE)")
        if 0 <= dte <= manage_at:
            alerts.append(f"MANAGE-BY   {tkr} ${strike:g}{kind[0].upper()}  {dte} DTE (manage at {manage_at})")
        if 0 <= dte <= 3 and s is not None:
            itm = (kind == "put" and s < strike) or (kind == "call" and s > strike)
            if itm:
                alerts.append(f"EXPIRY ITM  {tkr} ${strike:g}{kind[0].upper()}  {dte} DTE — assignment likely")
        if prem > 0:
            mid = opt_mid(tkr, strike, expiry, kind)
            if mid is not None and mid <= 0.5 * prem:
                alerts.append(f"TAKE PROFIT {tkr} ${strike:g}{kind[0].upper()}  mid ${mid:.2f} <= 50% of ${prem:.2f}")
    return alerts


def send_email(body):
    host = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("ALERT_SMTP_PORT", "587"))
    user = os.environ.get("ALERT_SMTP_USER")
    pw   = os.environ.get("ALERT_SMTP_PASS")
    frm  = os.environ.get("ALERT_EMAIL_FROM", user)
    to   = os.environ.get("ALERT_EMAIL_TO")
    if not (user and pw and to):
        print("SMTP not configured — printing only.")
        return
    msg = MIMEText(body)
    msg["Subject"] = f"Options alerts — {TODAY} ({body.count(chr(10))+1} items)"
    msg["From"] = frm
    msg["To"] = to
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as srv:
        srv.starttls(context=ctx)
        srv.login(user, pw)
        srv.sendmail(frm, [a.strip() for a in to.split(",")], msg.as_string())
    print(f"emailed {to}")


if __name__ == "__main__":
    found = check()
    if not found:
        print(f"{TODAY}: no alerts.")
    else:
        body = f"Position alerts for {TODAY}:\n\n" + "\n".join("• " + a for a in found)
        # Public repo -> Actions logs are public. Positions go to EMAIL only.
        print(f"{TODAY}: {len(found)} alert(s) found — details emailed, not logged. "
              f"(Configure ALERT_SMTP_* secrets to receive them.)")
        try:
            send_email(body)
        except Exception as e:
            print(f"email failed: {e}")
