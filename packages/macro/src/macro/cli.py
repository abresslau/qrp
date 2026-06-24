"""macro CLI — load macroeconomic / central-bank series.

    macro load        # fetch + upsert all configured series

Thin verb-based CLI (mirrors sym/rates/commodities) over ``ingest.run_ingest`` so the command reads
``macro load`` like every other data package, instead of ``python -m macro.ingest``. Exit codes:
0 ok, 2 operational failure.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from .db import connect
from .ingest import run_ingest


def _cmd_load(args: argparse.Namespace) -> int:
    try:
        conn = connect()  # macro owns its own database (DSN resolved by macro.config)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    try:
        result = run_ingest(conn)
    finally:
        conn.close()
    for s in result["series"]:
        print(f"  {s}")
    print(f"done: {len(result['series'])} series, {result['total_obs']} observations "
          f"({result['total_restated']} restated)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="macro", description="QRP macro — central-bank series.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("load", help="Fetch + upsert all configured macro series.")
    pl.set_defaults(func=_cmd_load)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
