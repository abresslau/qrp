"""``indices`` CLI — load benchmark index levels, recompute index returns, seed universe links.

Standalone entry point for the indices package. Opens its own ``indices`` DB plus read
connections to sym (identity) and universe (the roster) — the sym-orchestrated path (``sym
eod``) injects its own connections instead. Verbs:

    indices load                 # Yahoo levels + recompute returns + universe links + attach FIGIs
    indices load --attach-figis  # re-attach canonical FIGIs only (no level load)
    indices msci-import <path> --msci-code <c> [--variant PR|NR|GR] [--name ..] [--currency ..]
    indices msci-pull --all | (--msci-code <c> --variant PR|NR|GR [--currency ..] [--name ..])
    indices universe <universe_id>   # constituents + the primary reference index level, as-of today
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from indices.db import connect, sym_connect, universe_connect

DEFAULT_LOOKBACK = timedelta(days=430)


def _cmd_load(args: argparse.Namespace) -> int:
    from indices.figis import attach_index_figis
    from indices.levels import INDICES, YahooIndexLevelSource, load_index_levels
    from indices.links import link_universe_indices
    from indices.returns import recompute_index_returns

    with connect() as conn, sym_connect() as sym_conn:
        if args.attach_figis:
            attached, missing = attach_index_figis(sym_conn)
            print(f"figis: {attached} attached, {missing} missing")
            return 0
        ls = load_index_levels(conn, sym_conn, YahooIndexLevelSource(), INDICES)
        end = date.today()
        rs = recompute_index_returns(conn, start_date=end - DEFAULT_LOOKBACK, end_date=end)
        with universe_connect() as u_conn:
            lk = link_universe_indices(conn, sym_conn, u_conn)
        attached, _ = attach_index_figis(sym_conn)
        print(
            f"indices: {ls.instruments} instruments, {ls.levels_written} levels written, "
            f"{ls.deferred} deferred (MSCI), {ls.gaps} gaps; index returns: {rs.rows:,} rows / "
            f"{rs.series} series ({rs.extreme_rows:,} extreme rows); universe links: {lk.linked} "
            f"created; figis: {attached} attached"
        )
    return 0


def _cmd_levels(args: argparse.Namespace) -> int:
    """Load Yahoo index LEVELS + universe links + FIGIs — NO returns recompute.

    The level-load half of `load`, split out so an orchestrator (the eod DAG) can run levels and the
    derived returns as separate nodes (`index_levels` -> `index_returns`), mirroring equity's
    prices -> recompute split. Returns are produced by `indices returns`."""
    from indices.figis import attach_index_figis
    from indices.levels import INDICES, YahooIndexLevelSource, load_index_levels
    from indices.links import link_universe_indices

    with connect() as conn, sym_connect() as sym_conn:
        ls = load_index_levels(conn, sym_conn, YahooIndexLevelSource(), INDICES)
        with universe_connect() as u_conn:
            lk = link_universe_indices(conn, sym_conn, u_conn)
        attached, _ = attach_index_figis(sym_conn)
        print(
            f"index levels: {ls.instruments} instruments, {ls.levels_written} written, "
            f"{ls.deferred} deferred (MSCI), {ls.gaps} gaps; universe links: {lk.linked} created; "
            f"figis: {attached} attached (returns NOT recomputed — run `indices returns`)"
        )
    return 0


def _cmd_returns(args: argparse.Namespace) -> int:
    """Recompute index returns (fact_index_returns) over a window — derived from levels, no load.

    The returns half of `load`, split out for the eod DAG's `index_returns` node (mirrors equity's
    `sym recompute`). Window defaults to the standard lookback ending today."""
    from indices.returns import recompute_index_returns

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start = date.fromisoformat(args.start_date) if args.start_date else end - DEFAULT_LOOKBACK
    with connect() as conn:
        rs = recompute_index_returns(conn, start_date=start, end_date=end)
        print(
            f"index returns [{start}..{end}]: {rs.rows:,} rows / {rs.series} series "
            f"({rs.extreme_rows:,} extreme rows)"
        )
    return 0


def _cmd_msci_import(args: argparse.Namespace) -> int:
    from indices.msci import load_msci_file
    from indices.returns import recompute_index_returns

    with connect() as conn, sym_connect() as sym_conn:
        res = load_msci_file(
            conn, sym_conn, args.path, msci_code=args.msci_code, variant=args.variant,
            name=args.name, currency_code=args.currency,
        )
        end = date.today()
        rs = recompute_index_returns(conn, start_date=end - DEFAULT_LOOKBACK, end_date=end)
        print(
            f"msci import ({args.msci_code}) -> sym_id {res.sym_id}: parsed {res.parsed}, "
            f"{res.written} levels written; index returns: {rs.rows:,} rows / {rs.series} series "
            f"({rs.extreme_rows:,} extreme rows)"
        )
    return 0


def _cmd_msci_pull(args: argparse.Namespace) -> int:
    from indices.msci import MSCI_HISTORY_FLOOR, load_msci_pull, pull_all_msci
    from indices.returns import recompute_index_returns

    start = date.fromisoformat(args.start) if args.start else MSCI_HISTORY_FLOOR
    end = date.fromisoformat(args.end) if args.end else None
    with connect() as conn, sym_connect() as sym_conn:
        if args.all:
            res = pull_all_msci(conn, sym_conn, start_date=start, end_date=end)
            print(
                f"msci pull --all: {res.instruments} instruments, {res.pulled} pulled, "
                f"{res.written} levels; {len(res.failures)} failures"
            )
            for f in res.failures:
                print(f"  FAIL {f}")
        else:
            res = load_msci_pull(
                conn, sym_conn, msci_code=args.msci_code, variant=args.variant,
                currency=args.currency or "USD", name=args.name, start_date=start, end_date=end,
            )
            print(f"msci pull ({args.msci_code}) -> sym_id {res.sym_id}: "
                  f"parsed {res.parsed}, {res.written} levels written")
        end_d = date.today()
        recompute_index_returns(conn, start_date=end_d - DEFAULT_LOOKBACK, end_date=end_d)
    return 0


def _cmd_universe(args: argparse.Namespace) -> int:
    from indices.links import universe_with_index

    with connect() as conn, universe_connect() as u_conn:
        snap = universe_with_index(conn, u_conn, args.universe_id, date.today())
    print(
        f"{snap.universe_id} @ {snap.as_of_date}: {len(snap.members)} members; "
        f"index sym_id={snap.index_sym_id} level={snap.index_level} ({snap.index_level_date})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="indices", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    load = sub.add_parser("load", help="Yahoo levels + returns + universe links + FIGIs")
    load.add_argument("--attach-figis", action="store_true", help="re-attach FIGIs only")
    load.set_defaults(func=_cmd_load)

    levels = sub.add_parser("levels", help="Yahoo levels + links + FIGIs (no returns recompute)")
    levels.set_defaults(func=_cmd_levels)

    returns = sub.add_parser("returns", help="recompute index returns over a window (no load)")
    returns.add_argument("--start_date")
    returns.add_argument("--end_date")
    returns.set_defaults(func=_cmd_returns)

    imp = sub.add_parser("msci-import", help="import an MSCI level export (.csv/.xls/.xlsx)")
    imp.add_argument("path")
    imp.add_argument("--msci-code", required=True)
    imp.add_argument("--variant", choices=["PR", "NR", "GR"])
    imp.add_argument("--name")
    imp.add_argument("--currency")
    imp.set_defaults(func=_cmd_msci_import)

    pull = sub.add_parser("msci-pull", help="pull MSCI levels from the public EOD endpoint")
    pull.add_argument("--all", action="store_true", help="re-pull every existing MSCI instrument")
    pull.add_argument("--msci-code")
    pull.add_argument("--variant", choices=["PR", "NR", "GR"])
    pull.add_argument("--currency")
    pull.add_argument("--name")
    pull.add_argument("--start")
    pull.add_argument("--end")
    pull.set_defaults(func=_cmd_msci_pull)

    uni = sub.add_parser("universe", help="constituents + primary index level as-of today")
    uni.add_argument("universe_id")
    uni.set_defaults(func=_cmd_universe)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
