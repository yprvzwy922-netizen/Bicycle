"""
Position + risk alerts — runs in the daily GitHub Action (after the snapshot).

Emails you when something needs attention:
  • PUT / CALL TESTED  — a short option's strike is breached by the stock
  • MANAGE-BY DATE     — 1M trade at <=21 DTE, 3M at <=45 DTE (manual §5.1)
  • EXPIRY ITM         — <=3 DTE and in the money (assignment likely)
  • TAKE PROFIT        — a short option has captured >= 50% of its premium
  • RISK LIMIT BREACHED — any limit in public_app/risk.py, the same checks as the
                          Portfolio page's RISK STATUS strip
Positions are priced by public_app/book.py, risk by public_app/risk.py.

Email via SMTP. GitHub Action secrets:
  SUPABASE_URL, SUPABASE_KEY            (read trades / snapshots)
  ALERT_EMAIL_FROM, ALERT_EMAIL_TO      (addresses)
  ALERT_SMTP_HOST (default smtp.gmail.com), ALERT_SMTP_PORT (default 587)
  ALERT_SMTP_USER, ALERT_SMTP_PASS      (Gmail: an App Password, not your login)
If SMTP vars are missing it prints a count only. Public repo -> Actions logs are
public: positions, dollar values and addresses go to EMAIL only.
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText

import pandas as pd

from eod_feeds import bk, book_now, load_trades, rest, risk

TODAY = bk.today_et()


def position_alerts(book):
    """Short options only — a long call above its strike is good news, not an alert."""
    out = []
    shorts = book[book["_IS_SHORT"] & ~book["_IS_STOCK"]] if not book.empty else book
    for _, r in shorts.iterrows():
        tkr, k, s, dte = r["TICKER"], r["SHORT STRIKE"], r["SPOT"], r["DTE LEFT"]
        if bk._missing(k) or bk._missing(dte):
            continue
        kind = "P" if r["_IS_PUT"] else "C"
        itm = not bk._missing(s) and (s < k if kind == "P" else s > k)
        if itm:
            out.append(f"{'PUT' if kind == 'P' else 'CALL'} TESTED  {tkr} ${k:g}{kind}  spot ${s:.2f} "
                       f"{'below' if kind == 'P' else 'above'} strike ({int(dte)} DTE)")
        manage_at = 45 if r["TENOR"] == "3M" else 21
        if 0 <= dte <= manage_at:
            out.append(f"MANAGE-BY   {tkr} ${k:g}{kind}  {int(dte)} DTE (manage at {manage_at})")
        if 0 <= dte <= 3 and itm:
            out.append(f"EXPIRY ITM  {tkr} ${k:g}{kind}  {int(dte)} DTE — assignment likely")
        pct = r["% MAX PROFIT"]
        if not bk._missing(pct) and pct >= 0.50:
            out.append(f"TAKE PROFIT {tkr} ${k:g}{kind}  mid ${r['CURRENT MID']:.2f} = {pct:.0%} of premium captured")
    return out


def risk_alerts(trades, book):
    """Breached limits, evaluated exactly as the Portfolio page does."""
    if book.empty:
        return []
    contribs = rest("GET", "contributions", params={"select": "amount,units_issued"}) or []
    contributed = sum(float(c["amount"] or 0) for c in contribs)
    units = sum(float(c["units_issued"] or 0) for c in contribs)
    realized = float(pd.to_numeric(trades["REALIZED PNL"], errors="coerce").fillna(0).sum())
    nav = contributed + realized + float(pd.to_numeric(book["UNREAL PNL"], errors="coerce").sum())
    if nav <= 0:
        return []
    closes = risk.fetch_closes(lambda p: rest("GET", "snapshots", params=p),
                               set(trades["TICKER"].dropna().astype(str)) | {risk.BENCH})
    npu = nav / units if units > 0 else None
    hist = [float(x["nav_per_unit"]) for x in (rest("GET", "fund_snapshots", params={"select": "nav_per_unit"}) or [])
            if x.get("nav_per_unit") is not None]
    peak = max(hist + [npu]) if npu else None
    res = risk.evaluate(book, nav, risk.betas_from_closes(closes), npu=npu, peak_npu=peak,
                        available=bk.cash_summary(book, nav)["available"], events=False)
    return [f"{c['label']}: {risk.fmt_value(c)} (limit {risk.fmt_limit(c)}) — {c['detail']}"
            for c in res["checks"] if c["status"] == "breach"]


def send_email(subject, body):
    user, pw = os.environ.get("ALERT_SMTP_USER"), os.environ.get("ALERT_SMTP_PASS")
    to = os.environ.get("ALERT_EMAIL_TO")
    if not (user and pw and to):
        print("SMTP not configured — not sent.")
        return
    frm = os.environ.get("ALERT_EMAIL_FROM", user)
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = subject, frm, to
    with smtplib.SMTP(os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
                      int(os.environ.get("ALERT_SMTP_PORT", "587"))) as srv:
        srv.starttls(context=ssl.create_default_context())
        srv.login(user, pw)
        srv.sendmail(frm, [a.strip() for a in to.split(",")], msg.as_string())
    print("emailed (recipient redacted)")


if __name__ == "__main__":
    trades = load_trades()
    book = book_now(trades)
    pos = position_alerts(book)
    try:
        lim = risk_alerts(trades, book)
    except Exception as e:                      # never let the risk section block position alerts
        print(f"risk check skipped: {e}")
        lim = []
    if not pos and not lim:
        print(f"{TODAY}: no alerts.")
    else:
        parts = []
        if lim:
            parts.append("RISK LIMITS BREACHED (see Portfolio → RISK STATUS):\n" + "\n".join("• " + a for a in lim))
        if pos:
            parts.append("POSITIONS:\n" + "\n".join("• " + a for a in pos))
        print(f"{TODAY}: {len(pos)} position alert(s), {len(lim)} risk breach(es) — details emailed, not logged.")
        try:
            send_email(f"Options alerts — {TODAY} ({len(pos)} position, {len(lim)} risk)",
                       f"Alerts for {TODAY}:\n\n" + "\n\n".join(parts))
        except Exception as e:
            print(f"email failed: {e}")
