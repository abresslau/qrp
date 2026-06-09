"""Scheduler-agnostic EOD pipeline (Module-1 orchestration).

sym deliberately carries **no** Airflow/Prefect dependency. It exposes the daily
work as discrete *idempotent* steps plus a coarse ``run_eod`` runner; an external
scheduler either calls each ``sym <step>`` as its own task (fine-grained retries)
or runs ``sym eod`` (one cron line). Each step is error-isolated and reports a
short status; the run fails (non-zero exit) only if a *critical* step fails.

Tiered cadence: the daily core is monitor → delta → benchmarks → recompute →
validate; ``fundamentals`` (weekly) and ``snapshot-calendar`` (occasional) run on
their own schedules and are not in the daily default.
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


# The daily core, in order. monitor/benchmarks/validate are non-critical (a hiccup
# shouldn't fail the night); delta + recompute are the critical data path.
DAILY_STEPS: tuple[EodStep, ...] = (
    EodStep("monitor", "Discover index-universe membership changes", critical=False),
    EodStep("delta", "Incremental EOD price load (since each cursor)", critical=True),
    EodStep("benchmarks", "Refresh benchmark index levels + returns", critical=False),
    EodStep("fx", "Daily FX rate delta (Frankfurter)", critical=False),
    EodStep("recompute", "Materialize fact_returns (PR + TR)", critical=True),
    EodStep("validate", "Cross-layer integrity gate", critical=False),
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
    """The steps to run after applying ``only``/``skip`` (pure; preserves order)."""
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
    dispatches to the real implementations. ``dry_run`` prints the plan only. The
    summary is ``ok`` unless a *critical* step errored.
    """
    steps = select_steps(only=only, skip=skip)
    summary = EodSummary()
    if dry_run:
        summary.results = [StepResult(s.key, "planned", True, s.description) for s in steps]
        return summary
    run = runner or _default_runner(conn, as_of_date or date.today())
    crit = {s.key: s.critical for s in steps}
    for step in steps:
        try:
            detail = run(step.key)
            summary.results.append(StepResult(step.key, "ok", True, detail))
        except Exception as exc:  # noqa: BLE001 - isolate one step's failure
            summary.results.append(StepResult(step.key, "error", False, str(exc)[:300]))
    summary.ok = all(r.ok for r in summary.results if crit.get(r.key, True))
    return summary


def _default_runner(conn: object, as_of_date: date) -> Callable[[str], str]:
    """Map a step key to the real sym implementation (lazy imports; builds the source once)."""
    source_box: list[object] = []

    def source() -> object:
        if not source_box:
            from sym.config import source_key
            from sym.sources import get_source
            from sym.sources.yfinance_adapter import make_yahoo_symbol_resolver

            source_box.append(get_source(source_key(), symbol_for=make_yahoo_symbol_resolver(conn)))
        return source_box[0]

    def run(key: str) -> str:
        if key == "monitor":
            from sym.universe.monitor import run_monitor

            uids = [
                r[0]
                for r in conn.execute(
                    "SELECT universe_id FROM universe WHERE kind = 'index' ORDER BY universe_id"
                ).fetchall()
            ]
            joiners = leavers = 0
            for uid in uids:
                s = run_monitor(conn, uid)
                joiners += s.joiners
                leavers += s.leavers
            return f"{len(uids)} index universes; joiners={joiners} leavers={leavers}"
        if key == "delta":
            from sym.ingest.pipeline import run_load

            s = run_load(conn, source(), "delta", asof=as_of_date)
            return f"loaded={s.loaded} skipped={s.skipped} errored={s.errored} rows={s.rows}"
        if key == "benchmarks":
            from sym.benchmarks.levels import YahooIndexLevelSource, load_index_levels
            from sym.benchmarks.links import link_universe_benchmarks
            from sym.benchmarks.returns import recompute_index_returns
            from sym.returns.loader import DEFAULT_LOOKBACK

            lv = load_index_levels(conn, YahooIndexLevelSource())
            recompute_index_returns(conn, start=as_of_date - DEFAULT_LOOKBACK, end=as_of_date)
            link_universe_benchmarks(conn)
            return f"levels+{lv.levels_written}"
        if key == "fx":
            from sym.fx.ingest import delta_fx
            from sym.fx.source import FrankfurterSource
            from sym.universe.fundamentals import recompute_market_cap_usd

            s = delta_fx(conn, FrankfurterSource(), end=as_of_date)
            usd = recompute_market_cap_usd(conn) if s.inserted else 0
            return (
                f"inserted={s.inserted} skipped={s.skipped_existing} "
                f"implausible={s.implausible} market_cap_usd={usd}"
            )
        if key == "recompute":
            from sym.returns.loader import DEFAULT_LOOKBACK, load_returns

            s = load_returns(conn, start=as_of_date - DEFAULT_LOOKBACK, end=as_of_date)
            return f"securities={s.securities} rows={s.rows}"
        if key == "validate":
            from sym.validate.runner import summarize, validate

            _results, overall = validate(conn)
            p, w, f, _ = summarize(_results)
            return f"overall={overall} ({p} pass, {w} warn, {f} fail)"
        raise ValueError(f"unknown EOD step {key!r}")

    return run
