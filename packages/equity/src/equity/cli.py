"""equity CLI — thin standalone entry for the equity engine (prices · returns).

The primary operational entry remains `sym load` / `sym recompute` / `sym eod` (sym orchestrates the
engine, opening both the equity and sym connections — mirrors how `sym fx` was kept after the fx
split). This standalone `equity` CLI is a convenience for direct, equity-DB-only inspection; the
heavy load/recompute paths are exercised through sym so the identity/calendar reads stay wired.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="equity", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="report equity-DB row counts")

    args = parser.parse_args(argv)
    if args.cmd == "status":
        from equity.db import connect

        conn = connect()
        try:
            for t in ("prices_raw", "corporate_actions", "fact_returns", "fact_price_extremes"):
                n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608 (static)
                print(f"{t:24} {n:>14,}")
        finally:
            conn.close()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
