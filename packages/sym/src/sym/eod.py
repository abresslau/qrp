"""Scheduler-agnostic EOD pipeline (Module-1 orchestration).

sym deliberately carries **no** Airflow/Prefect dependency. It exposes the daily
work as discrete *idempotent* steps plus a coarse ``run_eod`` runner; an external
scheduler either calls each ``sym <step>`` as its own task (fine-grained retries)
or runs ``sym eod`` (one cron line). Each step is error-isolated and reports a
short status; the run fails (non-zero exit) only if a *critical* step fails.

Tiered cadence: the daily core is monitor → fill → map → classify → indices →
fx → recompute → validate; ``fundamentals`` (weekly) and ``snapshot-calendar``
(occasional) run on their own schedules and are not in the daily default.
(``map`` keeps the equity → ``instrument``/``sym_id`` bridge current so
cross-asset joins never drop a new security; ``classify`` runs right after ``map``
so a newly-joined member gets its GICS sector before ``validate`` checks
member-completeness — and before the next morning's heatmap.)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class EodStep:
    key: str
    description: str
    critical: bool = True


# The daily core, in order. monitor/map/indices/fx/validate/index-reconcile are non-critical (a
# hiccup shouldn't fail the night); fill + recompute are the critical data path.
DAILY_STEPS: tuple[EodStep, ...] = (
    EodStep("monitor", "Discover index-universe membership changes", critical=False),
    EodStep("fill", "Incremental EOD price fill (since each cursor)", critical=True),
    EodStep("map", "Map new securities to instrument identity (sym_id bridge)", critical=False),
    EodStep("classify", "GICS classification (financedatabase + fill chain)", critical=False),
    EodStep("indices", "Refresh index levels + returns", critical=False),
    EodStep("fx", "Daily FX rate fill (Frankfurter)", critical=False),
    EodStep("recompute", "Materialize fact_returns (PR + TR)", critical=True),
    EodStep("validate", "Cross-layer integrity gate", critical=False),
    EodStep("index-reconcile", "Index close vs source official (drift monitor, warn-only)",
            critical=False),
)


@dataclass
class StepResult:
    key: str
    status: str  # planned | ok | error
    ok: bool
    detail: str = ""


@dataclass
class EodSummary:
    results: list[StepResult] = field(default_factory=list)
    ok: bool = True


def select_steps(
    steps: tuple[EodStep, ...] = DAILY_STEPS,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[EodStep]:
    """The steps to run after applying ``only``/``skip`` (pure; preserves order).

    Unknown keys raise: a typo'd ``--steps fil`` (or a wrapper still passing a
    retired step name) would otherwise select an empty plan, run nothing, and
    exit 0 — a cron line that silently does nothing forever.
    """
    known = {s.key for s in steps}
    unknown = (set(only or []) | set(skip or [])) - known
    if unknown:
        raise ValueError(
            f"unknown EOD step(s): {', '.join(sorted(unknown))} "
            f"(known: {', '.join(s.key for s in steps)})"
        )
    selected = list(steps)
    if only:
        only_set = set(only)
        selected = [s for s in selected if s.key in only_set]
    if skip:
        skip_set = set(skip)
        selected = [s for s in selected if s.key not in skip_set]
    return selected


def run_eod(
    conn: object,
    *,
    as_of_date: date | None = None,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    dry_run: bool = False,
    runner: Callable[[str], str] | None = None,
) -> EodSummary:
    """Run the daily EOD steps, error-isolated; return per-step status.

    ``runner(key) -> detail`` executes one step (injected for testing); the default
    dispatches to the real implementations. ``dry_run`` returns the plan only. The
    summary is ``ok`` unless a *critical* step errored.

    Failure semantics: a NON-critical failure is isolated (the run continues); a
    CRITICAL failure aborts the remaining steps — running recompute/validate on
    top of a failed price fill would materialize derived data from inputs already
    known bad. Skipped steps are reported as ``skipped`` with the reason.
    """
    steps = select_steps(only=only, skip=skip)
    summary = EodSummary()
    if dry_run:
        summary.results = [StepResult(s.key, "planned", True, s.description) for s in steps]
        return summary
    run = runner or _default_runner(conn, as_of_date or date.today())
    crit = {s.key: s.critical for s in steps}
    aborted_by: str | None = None
    for step in steps:
        if aborted_by is not None:
            summary.results.append(
                StepResult(step.key, "skipped", False,
                           f"skipped: critical step {aborted_by!r} failed")
            )
            continue
        try:
            detail = run(step.key)
            summary.results.append(StepResult(step.key, "ok", True, detail))
        except Exception as exc:  # noqa: BLE001 - isolate one step's failure
            summary.results.append(StepResult(step.key, "error", False, str(exc)[:300]))
            if step.critical:
                aborted_by = step.key
    summary.ok = all(
        r.ok for r in summary.results if crit.get(r.key, True) and r.status != "skipped"
    )
    return summary


def _default_runner(conn: object, as_of_date: date) -> Callable[[str], str]:
    """Map a step key to the real sym implementation (lazy imports; builds the source once)."""
    source_box: list[object] = []

    def source() -> object:
        if not source_box:
            from equity.sources import get_source
            from equity.sources.yfinance_adapter import make_yahoo_symbol_resolver

            from sym.config import source_key

            source_box.append(get_source(source_key(), symbol_for=make_yahoo_symbol_resolver(conn)))
        return source_box[0]

    def run(key: str) -> str:
        if key == "monitor":
            from universe.db import connect as u_connect
            from universe.monitor import run_monitor

            from sym.universe.resolver import SymResolver

            # Membership lives in the universe DB now; sym (`conn`) supplies the identity resolver.
            with u_connect() as u_conn:
                resolver = SymResolver(conn)
                uids = [
                    r[0]
                    for r in u_conn.execute(
                        "SELECT universe_id FROM universe WHERE kind = 'index' ORDER BY universe_id"
                    ).fetchall()
                ]
                joiners = leavers = 0
                for uid in uids:
                    s = run_monitor(u_conn, uid, resolver)
                    joiners += s.joiners
                    leavers += s.leavers
            return f"{len(uids)} index universes; joiners={joiners} leavers={leavers}"
        if key == "fill":
            from equity.db import connect as equity_connect
            from equity.ingest.pipeline import FILL, run_load

            # Prices live in the equity DB now; the resolver/calendar read sym (`conn`). The daily
            # incremental is a forward fill (gap_aware defaults False).
            with equity_connect() as eq_conn:
                eq_conn.autocommit = True
                s = run_load(eq_conn, conn, source(), FILL, as_of_date=as_of_date)
            return f"loaded={s.loaded} skipped={s.skipped} errored={s.errored} rows={s.rows}"
        if key == "map":
            from sym.identity.instrument import backfill_equity_instruments

            b = backfill_equity_instruments(conn)
            return f"mapped new={b.created} existing={b.existed}"
        if key == "classify":
            from sym.classification.gics import read_active_coverage
            from sym.classification.registry import run_classification_chain

            # Unattended → llm_enabled=False (the opt-in, low-trust LLM pass never runs here).
            primary, results = run_classification_chain(conn, llm_enabled=False)
            classified, total = read_active_coverage(conn)
            touched = sum(
                r.summary.rows_inserted + r.summary.rows_updated + r.summary.rows_closed
                for r in results
                if r.summary is not None
            )
            errored = [r.name for r in results if r.error is not None]
            detail = (
                f"coverage {classified}/{total}; primary +{primary.rows_inserted} "
                f"~{primary.rows_updated}; fills touched {touched}"
            )
            if errored:
                # A source hiccup (network) is non-fatal — classify is non-critical — but
                # surface it in the step detail rather than swallowing it.
                detail += f"; source errors: {', '.join(errored)}"
            return detail
        if key == "indices":
            from equity.returns.loader import DEFAULT_LOOKBACK
            from indices.db import connect as indices_connect
            from indices.levels import YahooIndexLevelSource, load_index_levels
            from indices.links import link_universe_indices
            from indices.returns import recompute_index_returns
            from universe.db import connect as u_connect

            # Index levels/returns/links live in the indices DB — open it here (scoped to this
            # step); identity (instrument spine) reads sym (`conn`); the universe-existence check
            # reads the universe DB.
            with indices_connect() as ix_conn:
                lv = load_index_levels(ix_conn, conn, YahooIndexLevelSource())
                recompute_index_returns(
                    ix_conn, start_date=as_of_date - DEFAULT_LOOKBACK, end_date=as_of_date
                )
                with u_connect() as u_conn:
                    link_universe_indices(ix_conn, conn, u_conn)
            return f"levels+{lv.levels_written}"
        if key == "fx":
            from fx.db import connect as fx_connect
            from fx.ingest import fill_fx
            from fx.source import FrankfurterSource

            from sym.universe.fundamentals import recompute_market_cap_usd

            # FX lives in its own database — open it here (the sym `conn` is the EOD pipeline's;
            # the fx conn is scoped to this step). Daily forward fill (start_date=None -> tail
            # since the latest stored date), then recompute the sym-side market_cap_usd cross-DB.
            with fx_connect() as fx_conn:
                fx_conn.autocommit = True
                s = fill_fx(fx_conn, FrankfurterSource(), end_date=as_of_date)
                usd = recompute_market_cap_usd(conn, fx_conn) if s.inserted else 0
            return (
                f"[{s.start_date}..{s.end_date}] inserted={s.inserted} "
                f"skipped={s.skipped_existing} implausible={s.implausible} "
                f"market_cap_usd={usd}"
            )
        if key == "recompute":
            from equity.db import connect as equity_connect
            from equity.returns.loader import DEFAULT_LOOKBACK, load_returns

            # fact_returns lives in the equity DB; securities + calendar read sym (`conn`).
            with equity_connect() as eq_conn:
                s = load_returns(
                    eq_conn, conn, start_date=as_of_date - DEFAULT_LOOKBACK, end_date=as_of_date
                )
            return f"securities={s.securities} rows={s.rows}"
        if key == "validate":
            from sym.validate.runner import summarize, validate

            _results, overall = validate(conn)
            p, w, f, _ = summarize(_results)
            detail = f"overall={overall} ({p} pass, {w} warn, {f} fail)"
            if overall == "fail":
                # The step must REPORT failure — `[ok] validate: overall=FAIL` was a
                # gate that couldn't gate. Non-critical, so the run still exits 0.
                raise RuntimeError(detail)
            return detail
        if key == "index-reconcile":
            from indices.db import connect as indices_connect
            from indices.levels import YahooIndexLevelSource

            from sym.validate.index_levels import check_index_level_fidelity

            with indices_connect() as ix_conn:
                r = check_index_level_fidelity(conn, ix_conn, YahooIndexLevelSource())
            detail = f"{r.status} (checked={r.checked} warn={r.warnings} fail={r.failures})"
            if r.status == "fail":
                # Mirror validate: a real divergence (>= fail_bps) must REPORT, not show [ok].
                # Non-critical + warn-only by design, so a WARN (vendor noise) just surfaces.
                raise RuntimeError(detail)
            return detail
        raise ValueError(f"unknown EOD step {key!r}")

    return run
