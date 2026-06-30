"""commodities CLI — load daily commodity prices, inspect coverage, validate.

  commodity price load [--start_date YYYY-MM-DD] [--end_date ...] [--codes WTI,GOLD]
  commodity price coverage
  commodity validate

Mirrors the `rates` CLI: ``load`` with no ``--start_date`` is a tail-since-latest; with one it's a
windowed backfill. Connection uses autocommit so each per-day transaction commits durably.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import psycopg

from .db import connect
from .ingest import fill_prices
from .sources.yfinance_src import YFinanceCommoditySource
from .universe import BY_CODE, UNIVERSE

_RETURNS_LOOKBACK = timedelta(days=430)  # default recompute window when no dates given


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _resolve_codes(arg: str | None):
    if not arg:
        return UNIVERSE
    want = {c.strip().upper() for c in arg.split(",")}
    chosen = [BY_CODE[c] for c in want if c in BY_CODE]
    missing = sorted(want - {c.code for c in chosen})
    if missing:
        print(f"unknown codes {missing}; known: {sorted(BY_CODE)}", file=sys.stderr)
    return chosen


def _cmd_price_load(args: argparse.Namespace) -> int:
    try:
        start_date = _parse_date(args.start_date)
        end_date = _parse_date(args.end_date)
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    commodities = _resolve_codes(args.codes)
    if not commodities:
        return 1
    source = YFinanceCommoditySource(commodities=commodities)
    if args.band_pct is not None and args.band_pct <= 0:
        print("--band_pct must be > 0 (e.g. 0.5 = 50%)", file=sys.stderr)
        return 1
    try:
        conn = connect()
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    conn.autocommit = True
    print(f"commodities price load ({len(commodities)} commodities; "
          f"start={start_date or 'full-history'} end={end_date or 'today'}):")
    try:
        s = fill_prices(conn, source, start_date=start_date, end_date=end_date,
                        band_pct=args.band_pct)
    finally:
        conn.close()
    print(f"  [{s.start_date}..{s.end_date}] codes={len(s.codes)} days={s.days} "
          f"inserted={s.inserted} restated={s.restated} skipped={s.skipped_existing} "
          f"flagged={s.flagged}")
    if s.flagged_samples:
        print("  flagged:", "; ".join(s.flagged_samples))
    return 0


def _cmd_price_coverage(args: argparse.Namespace) -> int:
    from .gateway import DbCommoditiesGateway
    try:
        with connect() as conn:
            rows = DbCommoditiesGateway(conn).coverage()
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("commodity.price_daily is empty — run `commodity price load`")
        return 0
    for r in rows:
        print(f"  {r['code']:12} {r['sector']:16} days={r['days']:6} "
              f"[{r['start_date']}..{r['end_date']}] src={r['source']}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    from .validate import run_checks
    try:
        with connect() as conn:
            results = run_checks(conn)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    fails = 0
    for r in results:
        mark = {"PASS": "[ ok ]", "WARN": "[warn]", "FAIL": "[FAIL]"}.get(r["status"], "[ ?? ]")
        print(f"  {mark} {r['check']}: {r['detail']}")
        if r["status"] == "FAIL":
            fails += 1
    print(f"done: {len(results)} checks, {fails} failures")
    return 1 if fails else 0


def _cmd_returns(args: argparse.Namespace) -> int:
    """Recompute commodity trailing-window returns into commodity.return_daily over a window."""
    from .returns import recompute_commodity_returns

    try:
        end_date = _parse_date(args.end_date) or date.today()
        start_date = _parse_date(args.start_date) or (end_date - _RETURNS_LOOKBACK)
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    if start_date > end_date:
        print(f"start_date {start_date} is after end_date {end_date}", file=sys.stderr)
        return 1
    try:
        conn = connect()
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    try:
        s = recompute_commodity_returns(conn, start_date=start_date, end_date=end_date)
    finally:
        conn.close()
    print(f"commodity returns [{start_date}..{end_date}]: {s.rows:,} rows / {s.series} commodities")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="commodity", description="QRP commodities — daily prices")
    sub = p.add_subparsers(dest="cmd", required=True)

    price = sub.add_parser("price", help="price loads").add_subparsers(
        dest="price_cmd", required=True)
    pl = price.add_parser("load", help="Load continuous front-month prices from yfinance.")
    pl.add_argument("--start_date",
                    help="Window start (ISO). Omit for tail-since-latest / full history.")
    pl.add_argument("--end_date", help="Window end (ISO; default: today).")
    pl.add_argument("--codes", help="Comma list (e.g. WTI,GOLD); all if omitted.")
    pl.add_argument("--band_pct", type=float, default=None,
                    help="Optional day-over-day move band (0.5 = 50%%); routes outliers to review.")
    pl.set_defaults(func=_cmd_price_load)

    pc = price.add_parser("coverage", help="Per-commodity day count + date range.")
    pc.set_defaults(func=_cmd_price_coverage)

    pv = sub.add_parser("validate", help="Run data-quality checks.")
    pv.set_defaults(func=_cmd_validate)

    pr = sub.add_parser("returns", help="Recompute trailing-window returns over the settle series.")
    pr.add_argument("--start_date", help="Window start (ISO); default: end − ~430d.")
    pr.add_argument("--end_date", help="Window end (ISO); default: today.")
    pr.set_defaults(func=_cmd_returns)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
