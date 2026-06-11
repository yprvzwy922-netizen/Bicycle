-- Put-Selling Dashboard — Supabase schema
-- Paste this whole file into: Supabase Dashboard -> SQL Editor -> Run.
-- RLS is left DISABLED on purpose: the only client is the password-protected
-- app, and the API key lives in Streamlit Cloud secrets (never in code).

create table if not exists trades (
  id            bigint primary key,
  date_opened   text,
  ticker        text,
  strategy      text,
  short_strike  double precision,
  long_strike   double precision,
  expiry        text,
  dte_open      integer,
  contracts     integer,
  premium       double precision,
  cash_secured  double precision,
  max_loss      double precision,
  status        text,
  date_closed   text,
  close_price   double precision,
  realized_pnl  double precision,
  signal        text,
  notes         text
);

create table if not exists watchlist (
  ticker      text primary key,
  company     text,
  sector      text,
  bucket      text,
  conviction  integer,
  delta_band  text
);

-- Per-ticker daily history (builds the real IV-rank record over time)
create table if not exists snapshots (
  snap_date  text,
  ticker     text,
  spot       double precision,
  rv21       double precision,
  rv_rank    double precision,
  primary key (snap_date, ticker)
);

-- Portfolio-level daily history (equity curve)
create table if not exists portfolio_snapshots (
  snap_date       text primary key,
  open_positions  integer,
  total_credits   double precision,
  unreal_pnl      double precision,
  realized_pnl    double precision,
  cash_secured    double precision
);
