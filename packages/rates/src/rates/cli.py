"""`rates` CLI — fixed-income yield curves.

    rates curve load [--start_date ISO] [--end_date ISO] [--archive]
    rates curve coverage
    rates validate [--as_of_date ISO]

Exit codes: 0 ok · 1 user error · 2 operational failure.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import psycopg

from .db import connect
from .ingest import fill_curve
from .sources.boe import BoeCurveSource
from .sources.registry import build_registry
from .validate import FAIL, run_all


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _cmd_curve_load(args: argparse.Namespace) -> int:
    try:
        start_date = _parse_date(args.start_date)
        end_date = _parse_date(args.end_date) or date.today()
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    # backfill (explicit start) pulls the full-history archives; tail uses the latest bundle.
    archive = bool(args.archive or start_date is not None)
    try:
        with connect() as conn:
            conn.autocommit = True
            source = BoeCurveSource(archive=archive)
            # gate desynced days ONLY for the latest-bundle tail load; never for an archive backfill
            summary = fill_curve(
                conn, source, end_date=end_date, start_date=start_date, tail=not archive
            )
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — surface source/parse failures as op errors
        print(f"curve load failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"rates curve load [{summary.start_date} .. {summary.end_date}] "
        f"({'archive' if archive else 'latest'}): days={summary.days} inserted={summary.inserted} "
        f"restated={summary.restated} skipped={summary.skipped_existing} flagged={summary.flagged}"
    )
    if summary.gated_days:
        print(f"  gated (desynced, skipped): {', '.join(summary.gated_days[:10])}")
    if summary.flagged_samples:
        print(f"  flagged (-> review): {'; '.join(summary.flagged_samples)}")
    return 0


def _cmd_curve_load_world(args: argparse.Namespace) -> int:
    """Load every FX-matrix country (euro area by member) from the source registry. Attempt-all:
    one source failing (network/parse/layout drift) is logged and skipped, never blocking the rest.
    GB stays on `rates curve load` (the BoE archive is a separate, heavier fetch)."""
    try:
        start_date = _parse_date(args.start_date)
        end_date = _parse_date(args.end_date) or date.today()
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1

    registry = build_registry()
    if args.country:
        want = {c.strip().upper() for c in args.country.split(",")}
        registry = {k: v for k, v in registry.items() if k in want}
        if not registry:
            print(f"no registry source for {sorted(want)}; known: {sorted(build_registry())}",
                  file=sys.stderr)
            return 1

    try:
        conn = connect()
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    conn.autocommit = True

    ok = 0
    failed: list[str] = []
    total_sources = sum(len(v) for v in registry.values())
    print(f"rates curve load-world ({len(registry)} countries, {total_sources} sources; "
          f"start={start_date or 'full-history'} end={end_date}):")
    # attempt-all is per (country, source): one source failing never blocks the country's others.
    for code, sources in registry.items():
        for source in sources:
            try:
                # archive backfill semantics: these APIs return full history, never gate as a tail.
                # Wider band than the daily tail (20pp): a one-time backfill of monthly/sparse
                # official series must not reject real moves — only gross corruption (decimals).
                summary = fill_curve(
                    conn, source, end_date=end_date, start_date=start_date, tail=False, band_pp=20.0
                )
                print(f"  [ ok ] {code:3} {source.SOURCE:12} "
                      f"[{summary.start_date}..{summary.end_date}] days={summary.days} "
                      f"inserted={summary.inserted} restated={summary.restated} "
                      f"skipped={summary.skipped_existing} flagged={summary.flagged}")
                ok += 1
            except Exception as exc:  # noqa: BLE001 — attempt-all: one source never blocks the rest
                failed.append(f"{code}/{source.SOURCE}")
                print(f"  [FAIL] {code:3} {source.SOURCE:12} {type(exc).__name__}: {exc}",
                      file=sys.stderr)
    conn.close()
    tail = f"; failed: {', '.join(failed)}" if failed else ""
    print(f"done: {ok}/{total_sources} loaded{tail}")
    return 2 if failed and ok == 0 else 0


def _cmd_curve_coverage(args: argparse.Namespace) -> int:
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT country, curve_set, basis, rate_type, count(DISTINCT as_of_date) AS days,
                       min(as_of_date) AS first, max(as_of_date) AS last, count(*) AS nodes
                  FROM rates.curve_point
                 GROUP BY country, curve_set, basis, rate_type
                 ORDER BY country, curve_set, basis, rate_type
                """
            ).fetchall()
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print("rates.curve_point is empty — run `rates curve load` / `load-world`")
        return 0
    print(f"{'co':3} {'set':5} {'basis':10} {'type':8} {'days':>6} {'nodes':>8}  range")
    for co, cs, b, rt, days, first, last, nodes in rows:
        print(f"{co:3} {cs:5} {b:10} {rt:8} {days:>6} {nodes:>8}  {first}..{last}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        as_of_date = _parse_date(args.as_of_date)
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    try:
        with connect() as conn:
            results = run_all(conn, as_of_date=as_of_date)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 2
    worst_fail = False
    for r in results:
        mark = {"PASS": "  ok", "WARN": "warn", "FAIL": "FAIL"}.get(r.status, r.status)
        print(f"[{mark}] {r.name}: checked={r.checked} fail={r.failures} warn={r.warnings}"
              + (f" - {r.detail}" if r.detail else ""))
        for s in r.samples:
            print(f"        · {s}")
        if r.status == FAIL:
            worst_fail = True
    return 2 if worst_fail else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rates", description="QRP fixed-income yield curves.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_curve = sub.add_parser("curve", help="Yield-curve store: load, coverage.")
    curve_sub = p_curve.add_subparsers(dest="curve_command", required=True, metavar="<action>")

    c_load = curve_sub.add_parser("load", help="Load BoE UK yield curves (gilt + OIS).")
    c_load.add_argument("--start_date", help="Window start (ISO). Omit for tail-since-latest.")
    c_load.add_argument("--end_date", help="Window end (ISO; default: today).")
    c_load.add_argument("--archive", action="store_true",
                        help="Force the full-history archives (implied when --start_date is set).")
    c_load.set_defaults(func=_cmd_curve_load)

    c_world = curve_sub.add_parser(
        "load-world", help="Load all FX-matrix countries (euro area by member) from central banks.")
    c_world.add_argument("--country", help="Comma ISO-2 subset (e.g. DE,US,JP); all if omitted.")
    c_world.add_argument("--start_date", help="Window start (ISO). Omit for full history.")
    c_world.add_argument("--end_date", help="Window end (ISO; default: today).")
    c_world.set_defaults(func=_cmd_curve_load_world)

    c_cov = curve_sub.add_parser("coverage", help="Per-series day/node coverage + date range.")
    c_cov.set_defaults(func=_cmd_curve_coverage)

    p_val = sub.add_parser("validate", help="Run curve-store validation checks.")
    p_val.add_argument("--as_of_date", help="Date to validate as-of (ISO; default: today/latest).")
    p_val.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
