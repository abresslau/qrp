"""altdata CLI — load alternative-data series.

    altdata load [--start_date ISO] [--end_date ISO]   # ingest all curated series

Thin verb-based CLI (mirrors sym/rates/commodities/macro) over ``ingest.run_ingest`` so the command
reads ``altdata load`` like every other data package, instead of ``python -m altdata.ingest``. Needs
the sym DB (to resolve tickers → composite_figi) alongside its own. Exit codes: 0 ok, 1 bad arg,
2 operational failure.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import psycopg

from .db import connect
from .ingest import run_ingest


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _cmd_load(args: argparse.Namespace) -> int:
    try:
        start_date = _parse_date(args.start_date)
        end_date = _parse_date(args.end_date)
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    try:
        sym_conn = connect("sym")  # read-only: resolve tickers → composite_figi
        ad_conn = connect()        # altdata owns its own database
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    try:
        res = run_ingest(sym_conn, ad_conn, start_date=start_date, end_date=end_date)
    finally:
        sym_conn.close()
        ad_conn.close()
    for s in res["series"]:
        print(f"  {s}")
    print(f"done: {len(res['series'])} series, {res['total_obs']} observations")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="altdata", description="QRP alt-data — curated series.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("load", help="Ingest all curated alt-data series.")
    pl.add_argument("--start_date", help="Window start (ISO). Omit for the source default.")
    pl.add_argument("--end_date", help="Window end (ISO).")
    pl.set_defaults(func=_cmd_load)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
