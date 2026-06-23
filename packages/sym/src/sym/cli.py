"""Command-line entry point for sym.

Story 1.1 ships ``version`` and ``check-db``; Story 1.6 adds ``resolve`` (FIGI
assignment); Story 1.7 adds ``delist``; Story 1.8 adds ``classify`` (GICS); Story
2.1 adds ``snapshot-calendar``; Story 2.5 adds ``load`` (one loader: fill +
``--overwrite``, Story 2.11); Story 2.8 adds ``audit`` (was ``sweep``: trailing
re-fetch + drift flagging); Story 2.9 adds ``backup``; Story 3.4 adds ``recompute``
(the deterministic returns rebuild the DR runbook depends on); Story U1.1 adds
``universe`` (define/list research universes — the pluggable universe layer).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from sym import __version__


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"sym {__version__}")
    return 0


def _cmd_check_db(_args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect

    try:
        with connect() as conn:
            row = conn.execute("select version()").fetchone()
    except psycopg.OperationalError as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        return 1
    server_version = row[0] if row else "unknown"
    print(f"connected: {server_version}")
    return 0


def _cmd_resolve(_args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.identity.figi import HttpOpenFigiClient, OpenFigiError, resolve_universe
    from sym.identity.universe import load_seed_universe

    load_dotenv()
    securities = load_seed_universe()
    client = HttpOpenFigiClient(api_key=os.environ.get("OPENFIGI_API_KEY"))

    try:
        with connect() as conn:
            summary = resolve_universe(conn, client, securities)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    except OpenFigiError as exc:
        print(f"OpenFIGI unavailable: {exc}", file=sys.stderr)
        return 2

    print(
        f"resolved {len(securities)} seed names: "
        f"{summary.assigned} assigned ({summary.securities_created} new, "
        f"{summary.names_written} named), "
        f"{summary.no_figi_found} no_figi_found, "
        f"{summary.ambiguous_figi} ambiguous_figi, "
        f"{summary.share_class_conflict} share_class_conflict "
        f"({summary.review_enqueued} review rows enqueued)"
    )
    if summary.skipped_queued:
        print(_format_skipped_line(summary))
    return 0


def _format_skipped_line(summary) -> str:
    shown = ", ".join(summary.skipped_names[:10])
    more = len(summary.skipped_names) - 10
    suffix = f", +{more} more" if more > 0 else ""
    return (
        f"  {summary.skipped_queued} skipped — open review rows "
        f"({shown}{suffix}); see `sym review list`"
    )


def _cmd_review_list(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.identity.review_queue import list_reviews

    load_dotenv()
    try:
        with connect() as conn:
            items = list_reviews(conn, include_resolved=args.all)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    if not items:
        print("no review items" if args.all else "no open review items")
        return 0
    today = date.today()
    for it in items:
        age = (today - it["created_at"].date()).days
        state = "resolved" if it["resolved_at"] else f"open {age}d"
        print(
            f"  #{it['review_id']:<4} {it['source_key']:<28} {it['status']:<22} "
            f"candidates={it['candidate_count']} [{state}]"
            + (f" — {it['detail']}" if it["detail"] else "")
        )
    print(f"{len(items)} item(s)")
    return 0


def _cmd_review_resolve(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.identity.review_queue import ReviewQueueError, resolve_review

    if args.share_class_figi and not args.figi:
        print("--share-class-figi requires --figi", file=sys.stderr)
        return 1
    load_dotenv()
    try:
        with connect() as conn:
            conn.autocommit = True
            outcome = resolve_review(
                conn, args.review_id,
                composite_figi=args.figi, share_class_figi=args.share_class_figi,
            )
    except ReviewQueueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"review {args.review_id} {outcome}"
        + (f" — assigned {args.figi}" if outcome == "assigned" else
           " — input eligible again on the next resolve run "
           "(permanently-dead name? remove it from the seed file instead)")
    )
    return 0


def _cmd_names(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.identity.figi import HttpOpenFigiClient, OpenFigiError, backfill_names

    load_dotenv()
    client = HttpOpenFigiClient(api_key=os.environ.get("OPENFIGI_API_KEY"), max_retries=6)
    try:
        with connect() as conn:
            summary = backfill_names(conn, client, limit=args.limit)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    except OpenFigiError as exc:
        print(f"OpenFIGI unavailable: {exc}", file=sys.stderr)
        return 2
    print(
        f"named {summary.named}/{summary.attempted} unnamed securities "
        f"({summary.skipped_mismatch} ticker-recycled, {summary.skipped_unresolved} unresolved)"
    )
    return 0


def _cmd_delist(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.identity.lifecycle import delist_security

    try:
        delist_date = date.fromisoformat(args.delist_date)
    except ValueError as exc:
        print(f"invalid delist date {args.delist_date!r}: {exc}", file=sys.stderr)
        return 1

    try:
        with connect() as conn:
            found = delist_security(conn, args.composite_figi, delist_date=delist_date)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    if not found:
        print(f"no security with CompositeFIGI {args.composite_figi}", file=sys.stderr)
        return 1
    print(f"delisted {args.composite_figi} effective {delist_date.isoformat()}")
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    import psycopg

    from sym.classification.gics import (
        DEFAULT_COVERAGE_THRESHOLD,
        read_active_coverage,
    )
    from sym.classification.registry import run_classification_chain
    from sym.config import load_dotenv
    from sym.db import connect

    load_dotenv()

    try:
        with connect() as conn:
            # The full chain (financedatabase primary + the precedence-ordered fill specs)
            # via the single shared orchestrator — identical to the unattended EOD `classify`
            # step. Each fill pass is error-isolated inside this one committed transaction.
            summary, results = run_classification_chain(conn, llm_enabled=args.llm)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    # Whole-universe coverage AFTER every source has written — the honest
    # multi-source figure (primary `summary.coverage` only knows financedatabase).
    # Read on a FRESH connection so it runs AFTER the classification transaction has
    # committed (the run is one non-autocommit tx): a failure measuring coverage can
    # then never roll back the writes — it only costs us the AC #2 gate + the number.
    total_classified: int | None = None
    total_active: int | None = None
    try:
        with connect() as cov_conn:
            total_classified, total_active = read_active_coverage(cov_conn)
    except psycopg.Error as exc:
        print(
            f"coverage read failed (classification writes already committed): {exc}",
            file=sys.stderr,
        )

    print(
        f"classified {summary.classified}/{summary.active_total} active securities "
        f"({summary.coverage:.1%} coverage): "
        f"{summary.rows_inserted} inserted, {summary.rows_updated} updated, "
        f"{summary.rows_closed} closed, {summary.unchanged} unchanged, "
        f"{summary.failed} failed"
    )
    for r in results:
        if r.skipped:
            if r.skip_line:
                print(r.skip_line)
        elif r.error is not None:
            print(
                f"{r.name} fill pass FAILED (earlier passes unaffected): {r.error}",
                file=sys.stderr,
            )
        elif r.summary is None:
            print(f"{r.name} fill pass: nothing to fill (no classifiable actives) — not queried")
        else:
            for line in r.lines:
                print(line)
    if total_active is None or total_classified is None:
        # Writes committed; we just couldn't measure coverage — report and don't
        # gate (returning 2 here would falsely signal a failed classification run).
        print("whole-universe coverage (all sources): unavailable (coverage read failed)")
        return 0
    total_coverage = total_classified / total_active if total_active else 0.0
    print(
        f"whole-universe coverage (all sources): {total_classified}/{total_active} "
        f"= {total_coverage:.1%}"
    )
    if total_coverage < DEFAULT_COVERAGE_THRESHOLD:
        print(
            f"coverage {total_coverage:.1%} is below the "
            f"{DEFAULT_COVERAGE_THRESHOLD:.0%} threshold (AC #2)",
            file=sys.stderr,
        )
        return 2
    return 0


def _cmd_classify_opinions(args: argparse.Namespace) -> int:
    import psycopg

    from sym.classification.registry import run_opinion_matrix
    from sym.config import load_dotenv
    from sym.db import connect

    load_dotenv()
    try:
        with connect() as conn:
            results = run_opinion_matrix(conn, llm_enabled=args.llm)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    errored = 0
    for r in results:
        if r.skipped:
            if r.skip_line:
                print(r.skip_line)
        elif r.error is not None:
            errored += 1
            print(f"{r.name} opinion FAILED (others unaffected): {r.error}", file=sys.stderr)
        else:
            s = r.summary
            print(
                f"{r.name} opinion: {s.classified} classified of {s.in_scope} fetched; "
                f"{s.rows_inserted} inserted, {s.rows_updated} updated, {s.unchanged} unchanged, "
                f"{s.rows_closed} superseded, {s.failed} failed"
            )
    return 2 if errored else 0


def _cmd_snapshot_calendar(_args: argparse.Namespace) -> int:
    import psycopg

    from sym.calendar.snapshot import (
        ExchangeCalendarsSource,
        read_exchange_mics,
        snapshot_calendars,
    )
    from sym.config import load_dotenv
    from sym.db import connect

    load_dotenv()
    source = ExchangeCalendarsSource()
    # Cover near-future trading-day math without pulling decades past the horizon.
    end = date(date.today().year + 1, 12, 31)

    try:
        with connect() as conn:
            mics = read_exchange_mics(conn)
            summary = snapshot_calendars(conn, source, mics, end=end)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"snapshot of {summary.requested} exchanges "
        f"(exchange_calendars {source.library_version}): "
        f"{summary.versions_written} new versions ({summary.sessions_written} sessions), "
        f"{summary.unchanged} unchanged, {summary.empty} empty, "
        f"{summary.unknown_mic} unknown, {summary.failed} failed"
    )
    if summary.unknown_mics:
        unknown = ", ".join(summary.unknown_mics)
        print(f"  unknown to exchange_calendars: {unknown}", file=sys.stderr)
    return 0


def _cmd_load(args: argparse.Namespace) -> int:
    """The one loader: scope + date window + fill-or-overwrite.

    No ``--start_date`` → incremental from each security's cursor (the daily case).
    ``--start_date`` → fill from that date (gap-aware). ``--overwrite`` → re-fetch and
    replace the window.
    """
    import psycopg

    from sym.config import source_key
    from sym.db import connect
    from sym.ingest.pipeline import (
        OVERWRITE,
        plan_load,
        read_active_with_cursor,
        run_load,
    )
    from sym.sources import get_source
    from sym.sources.yfinance_adapter import make_yahoo_symbol_resolver

    try:
        start_date = date.fromisoformat(args.start_date) if args.start_date else None
        end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    if args.overwrite and start_date is None:
        print("--overwrite requires --start_date (the window to overwrite)", file=sys.stderr)
        return 1
    if start_date is not None and start_date > end_date:
        print(f"start_date {start_date} is after end_date {end_date}", file=sys.stderr)
        return 1

    scope = (args.scope or "all").strip()
    universe_id = figi = None
    if scope == "all":
        pass
    elif scope.startswith("universe:"):
        universe_id = scope[len("universe:") :].strip()
    elif scope.startswith("figi:"):
        figi = scope[len("figi:") :].strip()
    else:
        print(
            f"invalid --scope {scope!r}: use all | universe:<id> | figi:<COMPOSITE_FIGI>",
            file=sys.stderr,
        )
        return 1
    if universe_id == "" or figi == "":
        print(
            f"invalid --scope {scope!r}: the id after the prefix is empty",
            file=sys.stderr,
        )
        return 1

    mode, gap_aware = plan_load(start_date=start_date, overwrite=args.overwrite)
    try:
        with connect() as conn:
            conn.autocommit = True
            resolver = make_yahoo_symbol_resolver(conn)
            source = get_source(source_key(), symbol_for=resolver)
            if universe_id is not None:
                from sym.universe.ingest import run_universe_load

                kwargs = {"as_of_date": end_date, "limit": args.limit, "gap_aware": gap_aware}
                if mode == OVERWRITE:
                    kwargs["overwrite_start_date"] = start_date
                elif gap_aware:  # explicit-floor backfill
                    kwargs["history_floor"] = start_date
                summary = run_universe_load(conn, source, universe_id, mode, **kwargs)
            else:
                securities = None
                if figi is not None:
                    securities = [s for s in read_active_with_cursor(conn) if s[0] == figi]
                    if not securities:
                        print(f"{figi} not in the active master", file=sys.stderr)
                        return 1
                kwargs = {
                    "as_of_date": end_date, "limit": args.limit,
                    "securities": securities, "gap_aware": gap_aware,
                }
                if mode == OVERWRITE:
                    kwargs["overwrite_start_date"] = start_date
                elif gap_aware:  # explicit-floor backfill
                    kwargs["floor"] = start_date
                summary = run_load(conn, source, mode, **kwargs)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    verb = "load --overwrite" if mode == OVERWRITE else "load"
    window = f"[{start_date} .. {end_date}]" if start_date else f"[cursor .. {end_date}]"
    scope_lbl = (
        f"universe:{universe_id}" if universe_id else (f"figi:{figi}" if figi else "all")
    )
    print(
        f"{verb} {window} (scope={scope_lbl}) run #{summary.run_id} [{summary.status}]: "
        f"attempted={summary.attempted} loaded={summary.loaded} skipped={summary.skipped} "
        f"errored={summary.errored} rows={summary.rows}"
    )
    for figi_err, msg in summary.errors[:10]:
        print(f"  error {figi_err}: {msg[:80]}", file=sys.stderr)
    if args.limit is not None:
        print(
            f"  note: --limit {args.limit} capped this load to the first {summary.attempted} "
            "securities by composite_figi (smoke run). Omit --limit for a complete load.",
            file=sys.stderr,
        )
    if mode == OVERWRITE:
        print(
            "  note: replaced raw prices only (corporate actions are not re-pulled). "
            f"Run `sym recompute --start_date {start_date} --end_date {end_date}` to refresh returns."
        )
    return 2 if summary.errored else 0


def _cmd_recompute(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.returns.loader import DEFAULT_LOOKBACK, load_returns

    try:
        end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()
        start_date = (
            date.fromisoformat(args.start_date) if args.start_date
            else end_date - DEFAULT_LOOKBACK
        )
    except ValueError as exc:
        print(f"invalid date: {exc}", file=sys.stderr)
        return 1
    if start_date > end_date:
        print(f"start_date {start_date} is after end_date {end_date}", file=sys.stderr)
        return 1
    try:
        with connect() as conn:
            summary = load_returns(conn, start_date=start_date, end_date=end_date)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"recompute PR+TR [{start_date} .. {end_date}]: {summary.securities} securities, "
        f"{summary.rows:,} fact_returns rows, {summary.extreme_rows:,} fact_price_extremes rows"
    )
    return 0


def _cmd_backup(args: argparse.Namespace) -> int:
    import subprocess
    from pathlib import Path

    from sym.config import load_db_config
    from sym.dr import run_backup

    default = Path("backups") / f"sym-{date.today():%Y%m%d}.dump"
    output = Path(args.output) if args.output else default
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"backup failed: cannot create {output.parent}: {exc}", file=sys.stderr)
        return 1
    try:
        run_backup(load_db_config(), str(output))
    except FileNotFoundError as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"pg_dump failed (exit {exc.returncode})", file=sys.stderr)
        return 1
    size = output.stat().st_size
    print(f"backup written: {output} ({size:,} bytes) — restore: see docs/disaster-recovery.md")
    return 0


def _cmd_audit(_args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import source_key
    from sym.db import connect
    from sym.ingest.pipeline import run_audit
    from sym.sources import get_source
    from sym.sources.yfinance_adapter import make_yahoo_symbol_resolver

    key = source_key()
    try:
        with connect() as conn:
            resolver = make_yahoo_symbol_resolver(conn)
            source = get_source(key, symbol_for=resolver)
            summary = run_audit(conn, source, as_of_date=date.today())
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"audit ({key}) run #{summary.run_id} [{summary.status}]: "
        f"checked={summary.loaded} divergences={summary.flags} errored={summary.errored}"
    )
    for figi, msg in summary.errors[:10]:
        print(f"  error {figi}: {msg[:80]}", file=sys.stderr)
    return 2 if summary.errored else 0


def _cmd_fundamentals(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.sources.yfinance_adapter import make_yahoo_symbol_resolver
    from sym.universe.fundamentals import (
        YFinanceSharesHistorySource,
        all_resolved_member_figis,
        load_fundamentals_history,
        recompute_market_cap_usd,
        resolved_member_figis,
    )
    from sym.universe.registry import UniverseError

    if not args.all and not args.universe:
        print("specify --universe <id> or --all", file=sys.stderr)
        return 1
    if args.all and args.universe:
        print("--all and --universe are mutually exclusive", file=sys.stderr)
        return 1
    load_dotenv()
    try:
        with connect() as conn:
            conn.autocommit = True  # durable per-figi upserts (set before any query)
            figis = (
                all_resolved_member_figis(conn) if args.all
                else resolved_member_figis(conn, args.universe)
            )
            if args.limit:
                figis = figis[: args.limit]
            source = YFinanceSharesHistorySource(make_yahoo_symbol_resolver(conn))
            summary = load_fundamentals_history(conn, source, figis)
            usd_rows = recompute_market_cap_usd(conn)  # populate market_cap_usd for the new rows
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    scope = "all universes" if args.all else repr(args.universe)
    print(
        f"fundamentals for {scope}: "
        f"attempted={summary.attempted} loaded={summary.loaded} gaps={summary.gaps} "
        f"rows={summary.rows}; market_cap_usd recomputed ({usd_rows} rows)"
    )
    return 0


def _cmd_msci_import(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.indices.msci import load_msci_file
    from sym.indices.returns import recompute_index_returns
    from sym.returns.loader import DEFAULT_LOOKBACK

    load_dotenv()
    try:
        with connect() as conn:
            conn.autocommit = True
            summary = load_msci_file(
                conn, args.path, msci_code=args.msci_code, variant=args.variant, name=args.name,
                currency_code=args.currency,
            )
            end_date = date.today()
            rets = recompute_index_returns(
                conn, start_date=end_date - DEFAULT_LOOKBACK, end_date=end_date
            )
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"file not found: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"msci import ({args.msci_code}) -> sym_id {summary.sym_id}: "
        f"parsed {summary.parsed}, {summary.written} levels written; "
        f"index returns: {rets.rows:,} rows / {rets.series} series "
        f"({rets.extreme_rows:,} extreme rows)"
    )
    return 0


def _cmd_msci_pull(args: argparse.Namespace) -> int:
    import urllib.error

    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.indices.msci import MSCI_HISTORY_FLOOR, load_msci_pull
    from sym.indices.returns import recompute_index_returns
    from sym.returns.loader import DEFAULT_LOOKBACK

    load_dotenv()
    start_date = date.fromisoformat(args.start) if args.start else MSCI_HISTORY_FLOOR
    end_date = date.fromisoformat(args.end) if args.end else date.today()
    try:
        with connect() as conn:
            conn.autocommit = True
            summary = load_msci_pull(
                conn, msci_code=args.msci_code, variant=args.variant, currency=args.currency,
                name=args.name, start_date=start_date, end_date=end_date,
            )
            rets = recompute_index_returns(
                conn, start_date=end_date - DEFAULT_LOOKBACK, end_date=end_date
            )
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"MSCI request failed: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"msci pull ({args.msci_code} {args.variant}) -> sym_id {summary.sym_id}: "
        f"parsed {summary.parsed}, {summary.written} levels written; "
        f"index returns: {rets.rows:,} rows / {rets.series} series "
        f"({rets.extreme_rows:,} extreme rows)"
    )
    return 0


def _cmd_indices(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.indices.figis import attach_index_figis
    from sym.indices.levels import YahooIndexLevelSource, load_index_levels
    from sym.indices.links import link_universe_indices
    from sym.indices.returns import recompute_index_returns
    from sym.returns.loader import DEFAULT_LOOKBACK

    load_dotenv()
    end_date = date.today()
    start_date = end_date - DEFAULT_LOOKBACK
    try:
        with connect() as conn:
            conn.autocommit = True
            if args.attach_figis:  # standalone: just (re)attach canonical FIGIs
                attached, missing = attach_index_figis(conn)
                print(f"figis: {attached} attached, {missing} missing (load levels first)")
                return 0
            summary = load_index_levels(conn, YahooIndexLevelSource())
            rets = recompute_index_returns(conn, start_date=start_date, end_date=end_date)
            links = link_universe_indices(conn)
            attached, _ = attach_index_figis(conn)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"indices: {summary.instruments} instruments, "
        f"{summary.levels_written} levels written, {summary.deferred} deferred (MSCI), "
        f"{summary.gaps} gaps; index returns: {rets.rows:,} rows / {rets.series} series "
        f"({rets.extreme_rows:,} extreme rows); "
        f"universe links: {links.linked} created; figis: {attached} attached"
    )
    return 0


def _cmd_universe_index(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.indices.links import universe_with_index
    from sym.universe.registry import UniverseError

    as_of_date = date.today()
    if args.as_of_date:
        try:
            as_of_date = date.fromisoformat(args.as_of_date)
        except ValueError as exc:
            print(f"invalid --as_of_date {args.as_of_date!r}: {exc}", file=sys.stderr)
            return 1
    try:
        with connect() as conn:
            snap = universe_with_index(conn, args.universe_id, as_of_date)
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    level = f"{snap.index_level}" if snap.index_level is not None else "n/a"
    print(
        f"{args.universe_id!r} as-of {as_of_date.isoformat()}: {len(snap.members)} constituents; "
        f"primary index sym_id={snap.index_sym_id} level={level}"
    )
    return 0


def _cmd_eod(args: argparse.Namespace) -> int:
    from datetime import date

    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.eod import run_eod

    load_dotenv()
    as_of_date = date.today()
    if getattr(args, "as_of_date", None):
        try:
            as_of_date = date.fromisoformat(args.as_of_date)
        except ValueError as exc:
            print(f"invalid --as_of_date {args.as_of_date!r}: {exc}", file=sys.stderr)
            return 1
    only = [s.strip() for s in args.steps.split(",") if s.strip()] if args.steps else None
    skip = [s.strip() for s in args.skip.split(",") if s.strip()] if args.skip else None
    try:
        if args.dry_run:
            # The plan is static — printing what WOULD run must work with the DB down.
            summary = run_eod(None, as_of_date=as_of_date, only=only, skip=skip, dry_run=True)
        else:
            with connect() as conn:
                conn.autocommit = True
                summary = run_eod(conn, as_of_date=as_of_date, only=only, skip=skip)
    except ValueError as exc:  # unknown --steps/--skip key (a typo'd cron must be loud)
        print(f"eod: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    label = f"eod {'plan' if args.dry_run else 'run'} (as_of_date {as_of_date.isoformat()})"
    print(f"{label}:")
    for r in summary.results:
        marker = {"planned": "plan", "ok": " ok ", "error": "FAIL", "skipped": "skip"}.get(
            r.status, "?"
        )
        print(f"  [{marker}] {r.key}: {r.detail}")
    if not args.dry_run:
        print(f"overall: {'OK' if summary.ok else 'FAILED'}")
    return 0 if summary.ok else 2


def _cmd_validate(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.validate.results import FAIL
    from sym.validate.runner import format_report, validate

    try:
        with connect() as conn:
            results, overall = validate(conn, args.universe)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(format_report(results))
    return 2 if overall == FAIL else 0


def _cmd_index_reconcile(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.indices.levels import YahooIndexLevelSource
    from sym.validate.index_levels import check_index_level_fidelity
    from sym.validate.results import FAIL
    from sym.validate.runner import format_report

    load_dotenv()
    source = YahooIndexLevelSource()
    try:
        with connect() as conn:
            conn.autocommit = True
            result = check_index_level_fidelity(
                conn, source, warn_bps=args.warn_bps, fail_bps=args.fail_bps
            )
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(format_report([result]))
    return 2 if result.status == FAIL else 0


def _fx_currencies(args: argparse.Namespace) -> list[str] | None:
    if not args.currencies:
        return None
    # Drop empty segments ('EUR,,GBP' / trailing comma) — an empty-string currency
    # code would flow into FX source queries.
    codes = [c.strip().upper() for c in args.currencies.split(",") if c.strip()]
    return codes or None


def _fx_source(name: str):
    from sym.fx.source import EcbSdmxSource, FawazahmedSource, FrankfurterSource

    return {
        "frankfurter": FrankfurterSource,
        "ecb": EcbSdmxSource,
        "fawazahmed0": FawazahmedSource,
    }[name]()


def _cmd_fx(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect

    load_dotenv()
    today = date.today()
    try:
        with connect() as conn:
            conn.autocommit = True
            if args.fx_command == "review":
                from sym.fx.review import FxReviewError, list_fx_reviews, resolve_fx_review

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
                        detail = (" — rate inserted into fx_rate; the band un-wedges "
                                  "on the next load")
                    elif outcome == "accepted":
                        detail = (" — a rate for that key was ALREADY stored; nothing "
                                  "inserted (queue item was moot), row closed")
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
                        f"  #{it['review_id']:<4} {it['quote_currency']} "
                        f"{it['as_of_date']} rate={it['rate']} "
                        f"(prior={it['prior_rate']}){move} {it['reason']} "
                        f"[{state}] {it['source']}"
                    )
                print(f"{len(items)} item(s)")
                return 0
            if args.fx_command == "load":
                from sym.fx.ingest import fill_fx

                start_date = date.fromisoformat(args.start_date) if args.start_date else None
                end_date = date.fromisoformat(args.end_date) if args.end_date else today
                if start_date is not None and start_date > end_date:
                    print(f"start_date {start_date} is after end_date {end_date}", file=sys.stderr)
                    return 1
                s = fill_fx(
                    conn, _fx_source(args.source), end_date=end_date, start_date=start_date,
                    currencies=_fx_currencies(args),
                )
                # Use the resolved window (s.start_date), not the request: in the tail case
                # the caller passed start_date=None and fill_fx resolved the real start.
                print(
                    f"fx load [{s.start_date} .. {s.end_date}]: {s.currencies} currencies, "
                    f"inserted={s.inserted}, "
                    f"skipped={s.skipped_existing}, implausible={s.implausible}"
                )
                if s.flagged:
                    print(f"  flagged (rejected): {', '.join(s.flagged[:10])}")
                if s.inserted:  # new FX can fill previously-uncovered currency/dates
                    from sym.universe.fundamentals import recompute_market_cap_usd

                    print(f"  market_cap_usd recomputed ({recompute_market_cap_usd(conn)} rows)")
            elif args.fx_command == "coverage":
                from sym.validate.fx import check_fx_coverage

                r = check_fx_coverage(conn)
                print(f"fx coverage: {r.status} ({r.checked} currencies, {r.failures} fail, "
                      f"{r.warnings} warn)")
                for s in r.samples[:20]:
                    print(f"  {s}")
            elif args.fx_command == "divergence":
                from decimal import Decimal

                from sym.fx.reconcile import DEFAULT_DIVERGENCE, find_divergences

                threshold = Decimal(args.threshold) if args.threshold else DEFAULT_DIVERGENCE
                start_date = date.fromisoformat(args.start_date) if args.start_date else None
                rep = find_divergences(
                    conn, source_a=args.source_a, source_b=args.source_b,
                    threshold=threshold, start_date=start_date,
                    currencies=_fx_currencies(args),
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
            elif args.fx_command == "convert":
                from decimal import Decimal, InvalidOperation

                from sym.fx.convert import convert

                as_of_date = date.fromisoformat(args.as_of_date) if args.as_of_date else today
                try:
                    amount = Decimal(args.amount)
                except InvalidOperation:
                    print(f"invalid amount {args.amount!r}", file=sys.stderr)
                    return 1
                out = convert(conn, amount, args.from_ccy.upper(), args.to_ccy.upper(), as_of_date)
                if out is None:
                    print(f"convert: unavailable ({args.from_ccy.upper()}->"
                          f"{args.to_ccy.upper()} as-of {as_of_date}: no/stale rate)")
                    return 1
                print(f"{args.amount} {args.from_ccy.upper()} = {out:.4f} "
                      f"{args.to_ccy.upper()}  (as-of {as_of_date})")
            elif args.fx_command == "px":
                from sym.fx.restate import price_in_currency

                as_of_date = date.fromisoformat(args.as_of_date) if args.as_of_date else today
                px = price_in_currency(conn, args.figi, as_of_date, args.ccy.upper())
                if px is None:
                    print(f"px: unavailable ({args.figi} in {args.ccy.upper()} on {as_of_date})")
                    return 1
                print(f"{args.figi} adj close on {as_of_date} = {px:.4f} {args.ccy.upper()}")
            elif args.fx_command == "returns":
                from sym.fx.restate import returns_in_currency

                as_of_date = date.fromisoformat(args.as_of_date) if args.as_of_date else today
                res = returns_in_currency(conn, args.figi, as_of_date, args.ccy.upper())
                if not res:
                    print(f"returns: none for {args.figi} as-of {as_of_date}")
                    return 1
                print(f"{args.figi} returns in {args.ccy.upper()} (as-of {as_of_date}):")
                for code in ("1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"):
                    r = res.get(code)
                    if not r:
                        continue
                    pr = f"{float(r['pr']) * 100:.2f}%" if r["pr"] is not None else "n/a"
                    tr = f"{float(r['tr']) * 100:.2f}%" if r["tr"] is not None else "n/a"
                    print(f"  {code:5} PR={pr:>9}  TR={tr:>9}")
            elif args.fx_command == "mcap":
                from sym.marketcap import market_cap

                as_of_date = date.fromisoformat(args.as_of_date) if args.as_of_date else today
                mc = market_cap(
                    conn, args.figi, as_of_date, args.ccy.upper() if args.ccy else None
                )
                if mc.value is None:
                    print(f"mcap: unavailable ({args.figi} on {as_of_date})")
                    return 1
                print(
                    f"{args.figi} market cap on {as_of_date} = {mc.value:,.0f} {mc.currency} "
                    f"(= {mc.close_raw} {mc.local_currency} x {mc.shares:,.0f} shares "
                    f"as-of {mc.shares_as_of_date})"
                )
    except (ValueError, ArithmeticError) as exc:
        # Malformed --start_date/--end_date/--as_of_date/--since/--threshold across the
        # fx branches: a one-line message, never a raw traceback.
        print(f"invalid input: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_universe_add(args: argparse.Namespace) -> int:
    import json

    import psycopg

    from sym.db import connect
    from sym.universe.registry import UniverseError
    from sym.universe.store import add_universe

    config = None
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as exc:
            print(f"invalid --config JSON: {exc}", file=sys.stderr)
            return 1
    if args.from_path:
        config = {**(config or {}), "path": args.from_path}
    if args.index:
        config = {**(config or {}), "index": args.index}
    if args.rule:
        config = {**(config or {}), "rule": args.rule}
    if args.n is not None:
        config = {**(config or {}), "n": args.n}
    source_pref = None
    if args.source_pref:
        source_pref = [s.strip() for s in args.source_pref.split(",") if s.strip()]
    pit_from = None
    if args.pit_from:
        try:
            pit_from = date.fromisoformat(args.pit_from)
        except ValueError as exc:
            print(f"invalid --pit-from date {args.pit_from!r}: {exc}", file=sys.stderr)
            return 1

    try:
        with connect() as conn:
            inserted = add_universe(
                conn,
                args.universe_id,
                kind=args.kind,
                name=args.name,
                config=config,
                pit_valid_from=pit_from,
                source_pref=source_pref,
            )
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    if inserted:
        print(f"added universe {args.universe_id!r} (kind={args.kind})")
        return 0
    print(f"universe {args.universe_id!r} already exists", file=sys.stderr)
    return 0


def _cmd_universe_list(_args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.universe.store import list_universes

    try:
        with connect() as conn:
            universes = list_universes(conn)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    if not universes:
        print("no universes defined")
        return 0
    for u in universes:
        pit = u.pit_valid_from.isoformat() if u.pit_valid_from else "-"
        print(f"{u.universe_id:<16} {u.kind:<12} pit_from={pit:<12} {u.name}")
    return 0


def _cmd_universe_refresh(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.universe.refresh import refresh_universe
    from sym.universe.registry import UniverseError

    load_dotenv()
    try:
        with connect() as conn:
            summary = refresh_universe(conn, args.universe_id)
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"refreshed {args.universe_id!r}: appended={summary.appended} events, "
        f"resolved={summary.resolved} unresolved={summary.unresolved}, "
        f"projected {summary.figis} figis / {summary.intervals} intervals"
    )
    return 0


def _cmd_universe_members(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.universe.query import members
    from sym.universe.registry import UniverseError

    as_of_date = date.today()
    if args.as_of_date:
        try:
            as_of_date = date.fromisoformat(args.as_of_date)
        except ValueError as exc:
            print(f"invalid --as_of_date {args.as_of_date!r}: {exc}", file=sys.stderr)
            return 1
    try:
        with connect() as conn:
            figis = members(conn, args.universe_id, as_of_date)
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    for figi in sorted(figis):
        print(figi)
    print(
        f"{len(figis)} member(s) of {args.universe_id!r} as-of {as_of_date.isoformat()}",
        file=sys.stderr,
    )
    return 0


def _cmd_universe_monitor(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.universe.monitor import run_monitor
    from sym.universe.registry import UniverseError

    load_dotenv()
    try:
        with connect() as conn:
            summary = run_monitor(conn, args.universe_id)
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"monitored {args.universe_id!r} [{summary.status}]: "
        f"joiners={summary.joiners} leavers={summary.leavers} "
        f"applied={summary.applied} proposed={summary.proposed}"
        + (f" — {summary.detail}" if summary.detail else "")
    )
    return 0 if summary.status != "error" else 2


def _cmd_universe_coverage(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.universe.ingest import coverage
    from sym.universe.registry import UniverseError

    as_of_date = date.today()
    if args.as_of_date:
        try:
            as_of_date = date.fromisoformat(args.as_of_date)
        except ValueError as exc:
            print(f"invalid --as_of_date {args.as_of_date!r}: {exc}", file=sys.stderr)
            return 1
    try:
        with connect() as conn:
            cov = coverage(conn, args.universe_id, as_of_date)
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"coverage {args.universe_id!r} as-of {as_of_date.isoformat()}:\n"
        f"  members:        {cov.members_total} "
        f"({cov.resolved} resolved {cov.resolved_pct:.1%}, {cov.unresolved} unresolved)\n"
        f"  in master:      {cov.in_master}\n"
        f"  priced:         {cov.priced} of {cov.resolved} resolved ({cov.priced_pct:.1%})\n"
        f"  current ({as_of_date.isoformat()}): {cov.current_priced}/{cov.current_members} priced "
        f"({cov.current_priced_pct:.1%})"
    )
    return 0


def _cmd_universe_review(_args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.universe.review import build_digest, format_digest

    try:
        with connect() as conn:
            digest = build_digest(conn)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    print(format_digest(digest))
    return 0


def _cmd_universe_confirm(args: argparse.Namespace) -> int:
    import psycopg

    from sym.db import connect
    from sym.universe.gating import confirm_proposal, reject_proposal

    action = reject_proposal if args.reject else confirm_proposal
    try:
        with connect() as conn:
            conn.autocommit = True
            ok = action(conn, args.proposal_id)
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1
    verb = "rejected" if args.reject else "confirmed"
    if ok:
        print(f"{verb} proposal {args.proposal_id}")
        return 0
    print(f"proposal {args.proposal_id} not found or not pending", file=sys.stderr)
    return 1


def _cmd_universe_accuracy(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.universe.accuracy import DEFAULT_THRESHOLD, run_configured_accuracy_check
    from sym.universe.registry import UniverseError

    as_of_date = date.today()
    if args.as_of_date:
        try:
            as_of_date = date.fromisoformat(args.as_of_date)
        except ValueError as exc:
            print(f"invalid --as_of_date {args.as_of_date!r}: {exc}", file=sys.stderr)
            return 1
        if as_of_date != date.today():
            # A snapshot reference can't honor a point-in-time claim — the audit
            # row would assert a backdated check over data that is current.
            print(
                f"warning: snapshot references return CURRENT membership; the audit "
                f"row will be stamped {as_of_date.isoformat()} but compares today's data",
                file=sys.stderr,
            )
    threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLD
    if not 0 <= threshold <= 1:
        print(
            f"invalid --threshold {threshold!r}: must be a divergence fraction in [0, 1]",
            file=sys.stderr,
        )
        return 1
    load_dotenv()
    try:
        with connect() as conn:
            conn.autocommit = True
            result = run_configured_accuracy_check(
                conn, args.universe_id, as_of_date=as_of_date, threshold=threshold
            )
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    status = "ALARM" if result.alarm else "ok"
    print(
        f"accuracy {args.universe_id!r} vs {result.reference_source} [{status}]: "
        f"maintained={result.maintained_count} reference={result.reference_count} "
        f"divergence={result.divergence:.1%} threshold={result.threshold:.1%} "
        f"missing={len(result.missing)} extra={len(result.extra)}"
    )
    return 2 if result.alarm else 0


def _cmd_universe_reverse(args: argparse.Namespace) -> int:
    import psycopg

    from sym.config import load_dotenv
    from sym.db import connect
    from sym.universe.gating import reverse_change
    from sym.universe.registry import UniverseError

    try:
        effective_date = date.fromisoformat(args.effective_date)
    except ValueError as exc:
        print(f"invalid effective_date {args.effective_date!r}: {exc}", file=sys.stderr)
        return 1
    load_dotenv()
    try:
        with connect() as conn:
            conn.autocommit = True
            appended = reverse_change(
                conn, args.universe_id, args.raw_identifier, args.change, effective_date
            )
    except UniverseError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(f"database connection failed: {exc}", file=sys.stderr)
        return 1

    if appended:
        print(
            f"reversed {args.change} of {args.raw_identifier!r} in {args.universe_id!r} "
            f"effective {effective_date.isoformat()} "
            "(corrective event appended; projection rebuilt)"
        )
        return 0
    print(
        f"corrective for {args.raw_identifier!r} at {effective_date.isoformat()} "
        "already recorded — nothing appended",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sym",
        description="Global Equity Security Master + Market Data + Returns warehouse.",
    )
    parser.add_argument("--version", action="version", version=f"sym {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_version = sub.add_parser("version", help="Print the sym version.")
    p_version.set_defaults(func=_cmd_version)

    p_check = sub.add_parser(
        "check-db", help="Verify the database connection resolved from config."
    )
    p_check.set_defaults(func=_cmd_check_db)

    p_resolve = sub.add_parser(
        "resolve",
        help="Resolve the seed universe to CompositeFIGIs via OpenFIGI (decoupled from ingestion).",
    )
    p_resolve.set_defaults(func=_cmd_resolve)

    p_names = sub.add_parser(
        "names",
        help="Backfill company names (security_names) for securities created without one.",
    )
    p_names.add_argument("--limit", type=int, help="Cap the number of securities.")
    p_names.set_defaults(func=_cmd_names)

    p_delist = sub.add_parser(
        "delist",
        help="Soft-delete a security: set status=delisted + delist_date, retaining all history.",
    )
    p_delist.add_argument("composite_figi", help="CompositeFIGI of the security to delist.")
    p_delist.add_argument("delist_date", help="Delisting date (ISO YYYY-MM-DD).")
    p_delist.set_defaults(func=_cmd_delist)

    p_classify = sub.add_parser(
        "classify",
        help="Populate GICS classification for active securities from financedatabase.",
    )
    p_classify.add_argument(
        "--llm",
        action="store_true",
        help="Also run the opt-in LLM gap-fill pass (low-trust; reviewed "
        "llm_classifications.json artifact; source='llm') after the deterministic sources.",
    )
    p_classify.set_defaults(func=_cmd_classify)

    p_opinions = sub.add_parser(
        "classify-opinions",
        help="Multi-source opinion matrix: run EVERY source over ALL active securities and "
        "record each source's own GICS opinion in gics_source_opinion (gics_scd untouched). "
        "On-demand — NOT the nightly EOD (yahoo over the whole universe is slow).",
    )
    p_opinions.add_argument(
        "--llm",
        action="store_true",
        help="Also include the opt-in LLM artifact source in the matrix.",
    )
    p_opinions.set_defaults(func=_cmd_classify_opinions)

    p_snapshot_cal = sub.add_parser(
        "snapshot-calendar",
        help="Snapshot exchange_calendars trading days into the versioned trading_calendar table.",
    )
    p_snapshot_cal.set_defaults(func=_cmd_snapshot_calendar)

    p_load = sub.add_parser(
        "load",
        help="Load or re-upload raw prices for a scope over a date window. No --start_date = "
        "incremental from each security's cursor (daily); --start_date = fill from that date "
        "(gap-aware); --overwrite = re-fetch + replace the stored bars in the window.",
    )
    p_load.add_argument(
        "--scope",
        default="all",
        help="all | universe:<id> | figi:<COMPOSITE_FIGI> (default: all = the active master).",
    )
    p_load.add_argument("--start_date", help="Window start (ISO). Omit for incremental-from-cursor.")
    p_load.add_argument("--end_date", help="Window end (ISO; default: today).")
    p_load.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the window: re-fetch and replace stored bars (requires --start_date).",
    )
    p_load.add_argument("--limit", type=int, help="Cap the number of securities (smoke runs).")
    p_load.set_defaults(func=_cmd_load)

    p_audit = sub.add_parser(
        "audit",
        help="Re-fetch the trailing 90 days and flag where the source revised stored prices "
        "(read-only drift check; never overwrites).",
    )
    p_audit.set_defaults(func=_cmd_audit)

    p_backup = sub.add_parser(
        "backup",
        help="pg_dump source-of-truth data (excludes recomputable fact_returns) for DR.",
    )
    p_backup.add_argument("--output", help="Output path (default: backups/sym-YYYYMMDD.dump).")
    p_backup.set_defaults(func=_cmd_backup)

    p_recompute = sub.add_parser(
        "recompute",
        help="Materialize the price-return matrix into fact_returns over an as_of_date range.",
    )
    p_recompute.add_argument(
        "--start_date", dest="start_date", help="Start as_of_date (ISO; default: 1 year back)."
    )
    p_recompute.add_argument("--end_date", dest="end_date", help="End as_of_date (ISO; default: today).")
    p_recompute.set_defaults(func=_cmd_recompute)

    p_indices = sub.add_parser(
        "indices",
        help="Load index level series (S&P 500, IBOV, …) from Yahoo under sym_id.",
    )
    p_indices.add_argument(
        "--attach-figis",
        action="store_true",
        help="Only (re)attach canonical index FIGIs from the static map; skip the level load.",
    )
    p_indices.set_defaults(func=_cmd_indices)

    p_msci = sub.add_parser(
        "msci-import",
        help="Import an MSCI index-level export (CSV/Excel) into index_levels under sym_id.",
    )
    p_msci.add_argument("path", help="Path to the downloaded MSCI level file (.csv/.xls/.xlsx).")
    p_msci.add_argument("--msci-code", dest="msci_code", required=True, help="MSCI index code.")
    p_msci.add_argument(
        "--variant", choices=["PR", "NR", "GR"],
        help="Return variant — reconciles the xref with `msci-pull` (<code>:<VARIANT>). "
        "Omit only for a legacy bare-code import.",
    )
    p_msci.add_argument("--name", help="Instrument name (to create it on first import).")
    p_msci.add_argument("--currency", help="Instrument currency (ISO-4217, on first import).")
    p_msci.set_defaults(func=_cmd_msci_import)

    p_msci_pull = sub.add_parser(
        "msci-pull",
        help="Pull MSCI index levels DIRECTLY from MSCI's free EOD endpoint into index_levels "
        "(variant PR/NR/GR; from 1997). Polite/low-frequency; licence needed to redistribute.",
    )
    p_msci_pull.add_argument(
        "--msci-code", dest="msci_code", required=True, help="MSCI index code (e.g. 990100)."
    )
    p_msci_pull.add_argument(
        "--variant", required=True, choices=["PR", "NR", "GR"], help="Return variant."
    )
    p_msci_pull.add_argument("--currency", default="USD", help="ISO-4217 currency (default USD).")
    p_msci_pull.add_argument("--name", help="Instrument name (to create it on first pull).")
    p_msci_pull.add_argument(
        "--start", help="Start date (ISO; default 1997-01-01, the MSCI floor)."
    )
    p_msci_pull.add_argument("--end", help="End date (ISO; default today).")
    p_msci_pull.set_defaults(func=_cmd_msci_pull)

    p_eod = sub.add_parser(
        "eod",
        help="Run the daily EOD pipeline (monitor->fill->map->indices->fx->recompute->validate); "
        "scheduler-agnostic.",
    )
    p_eod.add_argument("--dry-run", action="store_true", help="Print the step plan, don't run.")
    p_eod.add_argument("--steps", help="Comma-separated subset to run (e.g. fill,recompute).")
    p_eod.add_argument("--skip", help="Comma-separated steps to skip.")
    p_eod.add_argument("--as_of_date", help="Run the pipeline as of this date (YYYY-MM-DD); default today.")
    p_eod.set_defaults(func=_cmd_eod)

    p_validate = sub.add_parser(
        "validate",
        help="Run the cross-layer validation suite (Epic V); non-zero exit on any failure.",
    )
    p_validate.add_argument("--universe", help="Scope completeness to one universe (else all).")
    p_validate.set_defaults(func=_cmd_validate)

    p_index_recon = sub.add_parser(
        "index-reconcile",
        help="Reconcile each index's stored latest close against the source's official "
        "close (live); warns/fails on divergence. Catches candle-vs-official gaps (e.g. ^BVSP).",
    )
    p_index_recon.add_argument(
        "--warn-bps", type=float, default=5.0, help="Warn at this divergence (basis points)."
    )
    p_index_recon.add_argument(
        "--fail-bps", type=float, default=50.0, help="Fail at this divergence (basis points)."
    )
    p_index_recon.set_defaults(func=_cmd_index_reconcile)

    p_fx = sub.add_parser(
        "fx", help="FX rates: load, coverage, divergence, convert, px, returns, mcap."
    )
    fx_sub = p_fx.add_subparsers(dest="fx_command", required=True, metavar="<action>")
    fx_load = fx_sub.add_parser(
        "load",
        help="Load USD-base rates: no --start_date = the tail since the latest stored date "
        "(daily); --start_date = fill from that floor (full history, resumable).",
    )
    fx_load.add_argument(
        "--start_date",
        help="Window start (ISO). Omit for tail-since-latest; 1999-01-04 is the ECB floor.",
    )
    fx_load.add_argument("--end_date", help="Window end (ISO; default: today).")
    fx_load.add_argument("--currencies", help="Comma-separated subset (default: all in `currency`).")
    fx_load.add_argument(
        "--source", default="frankfurter", choices=["frankfurter", "ecb", "fawazahmed0"],
        help="FX source (default: frankfurter; ecb is the reconcile, fawazahmed0 the breadth "
             "fallback).",
    )
    fx_load.set_defaults(func=_cmd_fx)
    fx_rev = fx_sub.add_parser(
        "review",
        help="Steward FX plausibility rejections: list open items, --accept (insert the "
        "rate, un-wedge the band) or --reject (vendor garbage) one.",
    )
    fx_rev.add_argument("--all", action="store_true", help="Include resolved rows.")
    fx_rev.add_argument("--accept", type=int, metavar="ID",
                        help="Accept: the move was genuine; insert into fx_rate and close. "
                        "Accept OLDEST-FIRST — the first accepted rate un-wedges the band "
                        "and the next load supersedes the rest of the queue itself.")
    fx_rev.add_argument("--reject", type=int, metavar="ID",
                        help="Reject as vendor garbage and close.")
    fx_rev.set_defaults(func=_cmd_fx)
    fx_cov = fx_sub.add_parser("coverage", help="FX coverage vs priced-instrument currencies.")
    fx_cov.set_defaults(func=_cmd_fx)
    fx_div = fx_sub.add_parser(
        "divergence", help="Cross-source rate divergence on overlapping (ccy, date) (FR4b)."
    )
    fx_div.add_argument("--source-a", dest="source_a", default="frankfurter",
                        help="Source under test (default: frankfurter).")
    fx_div.add_argument("--source-b", dest="source_b", default="ecb",
                        help="Reference source / denominator (default: ecb).")
    fx_div.add_argument("--threshold", help="Relative flag threshold (default: 0.005 = 0.5%%).")
    fx_div.add_argument("--start_date", help="Only compare dates on/after this ISO date.")
    fx_div.add_argument("--currencies", help="Comma-separated subset (default: all overlapping).")
    fx_div.set_defaults(func=_cmd_fx)
    fx_cv = fx_sub.add_parser("convert", help="Convert an amount between currencies as-of a date.")
    fx_cv.add_argument("amount", help="Amount to convert (e.g. 1000000).")
    fx_cv.add_argument("from_ccy", metavar="from", help="Source currency (e.g. BRL).")
    fx_cv.add_argument("to_ccy", metavar="to", help="Target currency (e.g. USD).")
    fx_cv.add_argument("--as_of_date", help="As-of date (ISO; default: today).")
    fx_cv.set_defaults(func=_cmd_fx)
    fx_px = fx_sub.add_parser("px", help="A security's adjusted close folded to a currency.")
    fx_px.add_argument("figi", help="CompositeFIGI.")
    fx_px.add_argument("ccy", help="Target currency (e.g. USD).")
    fx_px.add_argument("--as_of_date", help="Session date (ISO; default: today).")
    fx_px.set_defaults(func=_cmd_fx)
    fx_ret = fx_sub.add_parser("returns", help="Return windows restated to a currency.")
    fx_ret.add_argument("figi", help="CompositeFIGI.")
    fx_ret.add_argument("ccy", help="Target currency (e.g. USD).")
    fx_ret.add_argument("--as_of_date", help="As-of date (ISO; default: today).")
    fx_ret.set_defaults(func=_cmd_fx)
    fx_mc = fx_sub.add_parser("mcap", help="Derived market cap (price x shares) in LCY or a ccy.")
    fx_mc.add_argument("figi", help="CompositeFIGI.")
    fx_mc.add_argument("--ccy", help="Target currency (default: LCY / the security's own).")
    fx_mc.add_argument("--as_of_date", help="Date (ISO; default: today).")
    fx_mc.set_defaults(func=_cmd_fx)

    p_fundamentals = sub.add_parser(
        "fundamentals",
        help="Load market cap / shares outstanding for a universe's members (Story U5.1).",
    )
    p_fundamentals.add_argument("--universe", help="Universe whose members to load.")
    p_fundamentals.add_argument(
        "--all", action="store_true", help="Load all universe members (deduped union)."
    )
    p_fundamentals.add_argument("--limit", type=int, help="Cap the number of securities.")
    p_fundamentals.set_defaults(func=_cmd_fundamentals)

    from sym.universe.registry import VALID_KINDS

    p_universe = sub.add_parser(
        "universe", help="Define and inspect research universes (Story U1.1)."
    )
    u_sub = p_universe.add_subparsers(dest="universe_command", required=True, metavar="<action>")
    u_add = u_sub.add_parser("add", help="Register a universe.")
    u_add.add_argument("universe_id", help="Short stable slug (e.g. seed, sp500).")
    u_add.add_argument(
        "--kind", required=True, choices=VALID_KINDS, help="Provider archetype."
    )
    u_add.add_argument("--name", help="Human-readable label (default: the id).")
    u_add.add_argument("--config", help="Provider config as a JSON object.")
    u_add.add_argument("--from", dest="from_path", help="Source path (sets config.path).")
    u_add.add_argument("--index", help="Index key for an index universe (sets config.index).")
    u_add.add_argument("--rule", help="Criteria rule name (e.g. top_n_market_cap).")
    u_add.add_argument("--n", type=int, help="Criteria rule size N (e.g. top-N).")
    u_add.add_argument(
        "--source-pref",
        dest="source_pref",
        help="Comma-separated archetype preference (e.g. 'fmp,etf_holdings,wikipedia').",
    )
    u_add.add_argument("--pit-from", dest="pit_from", help="Trustworthy-history start (ISO date).")
    u_add.set_defaults(func=_cmd_universe_add)
    u_list = u_sub.add_parser("list", help="List registered universes.")
    u_list.set_defaults(func=_cmd_universe_list)
    u_refresh = u_sub.add_parser(
        "refresh", help="Run a universe's provider, resolve members, rebuild its membership."
    )
    u_refresh.add_argument("universe_id", help="The universe slug.")
    u_refresh.set_defaults(func=_cmd_universe_refresh)
    u_members = u_sub.add_parser("members", help="List a universe's members as-of a date.")
    u_members.add_argument("universe_id", help="The universe slug.")
    u_members.add_argument("--as_of_date", help="As-of date (ISO; default: today).")
    u_members.set_defaults(func=_cmd_universe_members)
    u_monitor = u_sub.add_parser(
        "monitor", help="Run the maintenance monitor for a universe (discover + append changes)."
    )
    u_monitor.add_argument("universe_id", help="The universe slug.")
    u_monitor.set_defaults(func=_cmd_universe_monitor)
    u_review = u_sub.add_parser(
        "review", help="Operator digest: gated changes, stale monitors, aging-unresolved, alarms."
    )
    u_review.set_defaults(func=_cmd_universe_review)
    u_coverage = u_sub.add_parser(
        "coverage", help="Report a universe's resolution + pricing coverage."
    )
    u_coverage.add_argument("universe_id", help="The universe slug.")
    u_coverage.add_argument("--as_of_date", help="As-of date (ISO; default: today).")
    u_coverage.set_defaults(func=_cmd_universe_coverage)
    u_bench = u_sub.add_parser(
        "index", help="Show a universe's constituents count + linked index level as-of."
    )
    u_bench.add_argument("universe_id", help="The universe slug.")
    u_bench.add_argument("--as_of_date", help="As-of date (ISO; default: today).")
    u_bench.set_defaults(func=_cmd_universe_index)
    u_confirm = u_sub.add_parser(
        "confirm", help="Confirm (or --reject) a pending gated membership-change proposal."
    )
    u_confirm.add_argument("proposal_id", type=int, help="The membership_proposal id.")
    u_confirm.add_argument(
        "--reject", action="store_true", help="Reject instead of confirm."
    )
    u_confirm.set_defaults(func=_cmd_universe_confirm)
    u_accuracy = u_sub.add_parser(
        "accuracy",
        help="Cross-check maintained membership against the configured independent "
        "reference source (config.accuracy_reference); exit 2 on alarm.",
    )
    u_accuracy.add_argument("universe_id", help="The universe slug.")
    u_accuracy.add_argument(
        "--as_of_date",
        help="As-of date stamped on the audit row (ISO; default: today). Snapshot "
        "references always return CURRENT membership regardless of this date.",
    )
    u_accuracy.add_argument(
        "--threshold",
        type=float,
        help="Alarm threshold as a divergence fraction (default: 0.05; an ETF-proxy "
        "reference gets +0.05 tolerance on top).",
    )
    u_accuracy.set_defaults(func=_cmd_universe_accuracy)
    u_reverse = u_sub.add_parser(
        "reverse",
        help="Reverse a wrongly-recorded membership change by appending a corrective "
        "event (the log stays append-only).",
    )
    u_reverse.add_argument("universe_id", help="The universe slug.")
    u_reverse.add_argument("raw_identifier", help="The member token (e.g. ticker:PETR4@BVMF).")
    u_reverse.add_argument(
        "change", choices=["join", "leave"], help="The wrong change being reversed."
    )
    u_reverse.add_argument("effective_date", help="The wrong change's effective date (ISO).")
    u_reverse.set_defaults(func=_cmd_universe_reverse)

    p_review = sub.add_parser(
        "review",
        help="Steward the securities review queue: list open items, resolve them "
        "(the queue GATES resolution runs until items are closed).",
    )
    r_sub = p_review.add_subparsers(dest="review_command", required=True, metavar="<command>")
    r_list = r_sub.add_parser("list", help="List review-queue items (open by default).")
    r_list.add_argument("--all", action="store_true", help="Include resolved items.")
    r_list.set_defaults(func=_cmd_review_list)
    r_resolve = r_sub.add_parser(
        "resolve",
        help="Close a review item: with --figi assigns the security first; "
        "without, dismisses it (eligible for auto-retry next run).",
    )
    r_resolve.add_argument("review_id", type=int, help="The review row id (see `review list`).")
    r_resolve.add_argument("--figi", help="Steward-picked CompositeFIGI to assign.")
    r_resolve.add_argument(
        "--share-class-figi", dest="share_class_figi", help="Optional ShareClassFIGI."
    )
    r_resolve.set_defaults(func=_cmd_review_resolve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
