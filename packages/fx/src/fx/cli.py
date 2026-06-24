"""`fx` CLI — the fx package's standalone command surface (own database).

FX-native verbs that need ONLY the fx database:

    fx load [--source frankfurter|ecb|fawazahmed0] [--start_date D] [--end_date D] [--currencies ..]
    fx review [--accept ID | --reject ID] [--all]
    fx divergence [--source_a ..] [--source_b ..] [--threshold ..] [--since D] [--currencies ..]
    fx convert <amount> <from_ccy> <to_ccy> [--as_of_date D]

Security-restatement verbs that need SYM data (px / returns / mcap / coverage) stay on `sym fx`
(they read sym prices/returns/securities and call into this package for the FX legs). `fx load`
loads rates only; the `fundamentals.market_cap_usd` recompute is a sym concern (run by `sym eod`'s
fx step or `sym fx load`).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from fx.db import connect


def _fx_currencies(arg: str | None) -> list[str] | None:
    if not arg:
        return None
    codes = [c.strip().upper() for c in arg.split(",") if c.strip()]
    return codes or None


def _fx_source(name: str):
    from fx.source import EcbSdmxSource, FawazahmedSource, FrankfurterSource

    return {
        "frankfurter": FrankfurterSource,
        "ecb": EcbSdmxSource,
        "fawazahmed0": FawazahmedSource,
    }[name]()


def _cmd_load(conn, args) -> int:
    from fx.ingest import fill_fx

    today = date.today()
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else today
    if start_date is not None and start_date > end_date:
        print(f"start_date {start_date} is after end_date {end_date}", file=sys.stderr)
        return 1
    s = fill_fx(
        conn, _fx_source(args.source), end_date=end_date, start_date=start_date,
        currencies=_fx_currencies(args.currencies),
    )
    print(
        f"fx load [{s.start_date} .. {s.end_date}]: {s.currencies} currencies, "
        f"inserted={s.inserted}, skipped={s.skipped_existing}, implausible={s.implausible}"
    )
    if s.flagged:
        print(f"  flagged (rejected): {', '.join(s.flagged[:10])}")
    return 0


def _cmd_review(conn, args) -> int:
    from fx.review import FxReviewError, list_fx_reviews, resolve_fx_review

    if args.accept is not None and args.reject is not None:
        print("--accept and --reject are mutually exclusive", file=sys.stderr)
        return 1
    if args.accept is not None or args.reject is not None:
        review_id = args.accept if args.accept is not None else args.reject
        try:
            outcome, rate_inserted = resolve_fx_review(
                conn, review_id, accept=args.accept is not None
            )
        except FxReviewError as exc:
            print(f"{exc}", file=sys.stderr)
            return 1
        if outcome == "accepted" and rate_inserted:
            detail = " — rate inserted into fx_rate; the band un-wedges on the next load"
        elif outcome == "accepted":
            detail = (" — a rate for that key was ALREADY stored; nothing inserted "
                      "(queue item was moot), row closed")
        else:
            detail = " — vendor garbage, closed"
        print(f"fx review {review_id} {outcome}{detail}")
        return 0
    items = list_fx_reviews(conn, include_resolved=args.all)
    if not items:
        print("no fx rejections" if args.all else "no open fx rejections")
        return 0
    for it in items:
        state = it["resolution"] or "open"
        move = (f" move={it['relative_move']:.1%}"
                if it["relative_move"] is not None else "")
        print(
            f"  #{it['review_id']:<4} {it['quote_currency']} {it['as_of_date']} "
            f"rate={it['rate']} (prior={it['prior_rate']}){move} {it['reason']} "
            f"[{state}] {it['source']}"
        )
    print(f"{len(items)} item(s)")
    return 0


def _cmd_divergence(conn, args) -> int:
    from decimal import Decimal

    from fx.reconcile import DEFAULT_DIVERGENCE, find_divergences

    threshold = Decimal(args.threshold) if args.threshold else DEFAULT_DIVERGENCE
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    rep = find_divergences(
        conn, source_a=args.source_a, source_b=args.source_b,
        threshold=threshold, start_date=start_date,
        currencies=_fx_currencies(args.currencies),
    )
    print(
        f"fx divergence: {rep.source_a} vs {rep.source_b} "
        f"(threshold {threshold * 100:.3f}%): compared={rep.compared}, "
        f"diverged={rep.diverged}, max={rep.max_rel * 100:.3f}%"
    )
    for d in rep.worst[:20]:
        print(
            f"  {d.currency}@{d.as_of_date}: {rep.source_a}={d.rate_a} "
            f"{rep.source_b}={d.rate_b}  (delta {d.rel * 100:.3f}%)"
        )
    return 1 if rep.diverged else 0


def _cmd_convert(conn, args) -> int:
    from decimal import Decimal, InvalidOperation

    from fx.convert import convert

    today = date.today()
    as_of_date = date.fromisoformat(args.as_of_date) if args.as_of_date else today
    try:
        amount = Decimal(args.amount)
    except InvalidOperation:
        print(f"invalid amount {args.amount!r}", file=sys.stderr)
        return 1
    out = convert(conn, amount, args.from_ccy.upper(), args.to_ccy.upper(), as_of_date)
    if out is None:
        print(f"convert: unavailable ({args.from_ccy.upper()}->{args.to_ccy.upper()} "
              f"as-of {as_of_date}: no/stale rate)")
        return 1
    print(f"{args.amount} {args.from_ccy.upper()} = {out:.4f} "
          f"{args.to_ccy.upper()}  (as-of {as_of_date})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fx", description="QRP fx — USD-base FX rates (own database).")
    sub = p.add_subparsers(dest="fx_command", required=True)

    lo = sub.add_parser("load", help="Load USD-base rates (immutable insert; skips existing).")
    lo.add_argument("--source", default="frankfurter",
                    choices=["frankfurter", "ecb", "fawazahmed0"])
    lo.add_argument("--start_date")
    lo.add_argument("--end_date")
    lo.add_argument("--currencies", help="comma-separated subset (default: all in fx.currency)")

    rev = sub.add_parser("review", help="Steward the FX plausibility rejection queue.")
    rev.add_argument("--accept", type=int)
    rev.add_argument("--reject", type=int)
    rev.add_argument("--all", action="store_true", help="include resolved rows")

    dv = sub.add_parser("divergence", help="Compare two sources for disagreement.")
    dv.add_argument("--source_a", default="frankfurter")
    dv.add_argument("--source_b", default="ecb")
    dv.add_argument("--threshold")
    dv.add_argument("--start_date", dest="start_date")
    dv.add_argument("--currencies")

    cv = sub.add_parser("convert", help="Convert an amount between currencies as-of a date.")
    cv.add_argument("amount")
    cv.add_argument("from_ccy")
    cv.add_argument("to_ccy")
    cv.add_argument("--as_of_date")
    return p


def main(argv: list[str] | None = None) -> int:
    import psycopg

    args = _build_parser().parse_args(argv)
    dispatch = {
        "load": _cmd_load,
        "review": _cmd_review,
        "divergence": _cmd_divergence,
        "convert": _cmd_convert,
    }
    try:
        with connect() as conn:
            conn.autocommit = True
            return dispatch[args.fx_command](conn, args)
    except (ValueError, ArithmeticError) as exc:
        print(f"invalid input: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
