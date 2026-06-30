"""A daily schedule for sym's end-of-day pipeline — Dagster as a *trigger + observer only*.

Deliberately minimal: Dagster does NOT model the EOD steps as a workflow. ``sym`` already owns the
daily sequence (monitor → fill → map → classify → indices → fx → recompute → validate); this fires the
**exact same** `sym eod` CLI an operator runs by hand, then retains the run log and auto-retries
transient failures. There is no Dagster op-graph, asset-job, or sensor here — one op, one job,
one schedule.

**Manual running is unchanged and always available** (no Dagster needed):

    uv run sym eod                 # the whole pipeline
    uv run sym eod --steps fill    # a subset
    uv run sym eod --dry-run       # just the plan

…or in the Dagster UI: launch the ``sym_eod`` job, or materialize an individual sym asset (each
runs its own `sym` subcommand). The schedule ships **STOPPED** — enable it in the Dagster UI
(Schedules tab) when you want unattended runs.
"""

import subprocess
import sys
import time
from datetime import date, timedelta

from dagster import (
    Config,
    DefaultScheduleStatus,
    RetryPolicy,
    ScheduleDefinition,
    graph,
    job,
    op,
)

from .bucket_jobs import _BUILDERS, _run_cmd, resolve_window
from .sym_run import repo_root


class EodConfig(Config):
    """Run-time config for the EOD ops.

    A ``[start_date, end_date]`` business-date window (YYYY-MM-DD). All blank → ``end_date`` = today
    (the scheduled tick) and ``start_date`` = ``end_date`` (a single day — the scheduled nightly run
    is unchanged). Set ``start_date``/``end_date`` in the Dagster launchpad to backfill a gap;
    ``as_of_date`` stays a back-compat single-date alias (start = end = as_of_date). Resolution is the
    shared ``bucket_jobs.resolve_window``.
    """

    start_date: str = ""
    end_date: str = ""
    as_of_date: str = ""


@op(
    # Recovery: auto-retry transient EOD failures (network/lock). sym's steps are idempotent.
    retry_policy=RetryPolicy(max_retries=2, delay=300),
)
def sym_eod(context, config: EodConfig) -> None:
    """Run the `sym eod` CLI (sym owns the step orchestration). Manual: `uv run sym eod [--as_of_date DATE]`.

    Note: `sym eod` exits non-zero only when a *critical* step (fill/recompute) fails — that is
    what turns the Dagster run red and triggers the retry. Non-critical hiccups (monitor / fx /
    indices / validate) still exit 0 by sym's design ("a hiccup shouldn't fail the night"), so
    their status lives in the captured run log (the `[FAIL] …` lines), not the run's red/green.
    """
    as_of_date = config.as_of_date.strip()
    if not as_of_date:
        # Prefer the SCHEDULED execution time over the worker's wall clock: the tick
        # fires 18:30 America/New_York, but a host at UTC+1 or later has already
        # rolled past midnight — date.today() would run Monday's close as Tuesday.
        scheduled = getattr(context, "run", None)
        tick = (scheduled.tags.get("dagster/scheduled_execution_time") if scheduled else None)
        as_of_date = (tick or "")[:10] or date.today().isoformat()
    cmd = [sys.executable, "-m", "sym.cli", "eod", "--as_of_date", as_of_date]
    context.log.info(f"running: sym eod --as_of_date {as_of_date}")
    started = time.monotonic()
    # Generous cap (2h): one hung vendor socket must not block the slot forever —
    # the RetryPolicy only fires when the op actually fails.
    proc = subprocess.run(
        cmd, cwd=str(repo_root()), capture_output=True, text=True, timeout=7200
    )
    tail = (proc.stdout or "")[-4000:]
    if proc.returncode != 0:
        # The actionable `[FAIL] <step>` detail is on stdout; log it at error on failure.
        context.log.error(f"sym eod FAILED (exit {proc.returncode}):\n{tail}\n{(proc.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym eod` exited {proc.returncode}")
    context.log.info(tail)
    context.log.info(f"sym eod ok in {round(time.monotonic() - started, 1)}s")


@job(description="sym end-of-day pipeline — runs the `sym eod` CLI. Manual: `uv run sym eod`.")
def sym_eod_job():
    sym_eod()


# Weekdays 18:30 America/New_York — after the US equity close (+ buffer); DST-aware so it stays
# "after close" year-round. Timezone is ALWAYS set explicitly (never the silent UTC default) —
# this is a hard requirement for every schedule. STOPPED until enabled in the UI.
sym_eod_daily = ScheduleDefinition(
    name="sym_eod_daily",
    job=sym_eod_job,
    cron_schedule="30 18 * * 1-5",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.STOPPED,
)


@op(retry_policy=RetryPolicy(max_retries=2, delay=300))
def commodities_load(context) -> None:
    """Tail-load the commodity continuous front-month series then validate (commodities owns its
    steps; trigger-only here).

    Manual: ``uv run commodities price load`` then ``uv run commodities validate``. The load tails a
    short window (last ~12 days, idempotent equal-value rows skip) so the daily tick is a light
    top-up, not a full re-pull. A FAIL in validate (exit 2) turns the run red and triggers the retry.
    """
    root = str(repo_root())
    scheduled = getattr(context, "run", None)
    tick = (scheduled.tags.get("dagster/scheduled_execution_time") if scheduled else None)
    end = (tick or "")[:10] or date.today().isoformat()
    start = (date.fromisoformat(end) - timedelta(days=12)).isoformat()
    load = subprocess.run(
        [sys.executable, "-m", "commodity.cli", "price", "load",
         "--start_date", start, "--end_date", end],
        cwd=root, capture_output=True, text=True, timeout=3600,
    )
    context.log.info((load.stdout or "")[-4000:])
    if load.returncode != 0:
        context.log.error(
            f"commodities price load FAILED (exit {load.returncode}):\n{(load.stderr or '')[-2000:]}")
        raise RuntimeError(f"`commodities price load` exited {load.returncode}")
    val = subprocess.run(
        [sys.executable, "-m", "commodity.cli", "validate"],
        cwd=root, capture_output=True, text=True, timeout=600,
    )
    context.log.info((val.stdout or "")[-4000:])
    if val.returncode != 0:
        raise RuntimeError(f"`commodities validate` exited {val.returncode} (a check FAILED)")


@job(
    name="commodities",
    description="Daily commodity prices (Tier-A vendor continuous front-month) — tail load + "
    "validate across the whole universe (energy / metals / grains / softs / livestock). "
    "Manual: `uv run commodities price load`.",
)
def commodities_job():
    commodities_load()


# Weekdays 18:30 America/New_York — after the US futures (NYMEX/COMEX/CBOT/ICE) settle and the
# vendor continuous series refresh. Timezone ALWAYS explicit (the hard requirement). STOPPED until
# enabled in the Dagster UI.
commodities_daily = ScheduleDefinition(
    name="commodities_daily",
    job=commodities_job,
    cron_schedule="30 18 * * 1-5",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.STOPPED,
)


# ---- `eod` as a readable DAG: one op per bucket, grouped into data-load and calculations phases ----
# The job is a graph-of-graphs so the Dagster UI shows two collapsible PHASE boxes — `eod_data` (every
# bucket as its OWN node: equity_prices, fx, index_levels, commodities, rates, macro, alt_data,
# fundamental, universe) and `eod_calculations` (returns_recompute → validate). The window is resolved
# ONCE (`resolve_eod_window`) and threaded as "start/end" into every node; a fan-in (`data_complete`)
# makes the calc phase wait for ALL data nodes. Each node shells the SAME CLI as before — only the op
# decomposition is new, so behavior is unchanged. NOTE: launchpad config now lives under the
# `resolve_eod_window` op (was `eod_data`).

# The six separate-package buckets — each runs its bucket command builder (bucket_jobs._BUILDERS), so
# `eod` and the per-bucket jobs share ONE definition and can't drift. equity_prices / fx / index_levels
# are the sym-owned nodes (run via `sym eod --steps`, preserving the monitor→fill→map→classify chain).
_EOD_DATA_BUCKETS = ("rates", "commodities", "macro", "alt_data", "fundamental", "universe")

EOD_TIMEOUT_S = 7200
_EOD_RETRY = RetryPolicy(max_retries=2, delay=300)


def _sym_eod_steps(context, steps: str, end: str, *, critical: bool) -> None:
    """Run ``sym eod --as_of_date <end> --steps <steps>``; attempt-all unless ``critical`` (then raise
    on a non-zero exit). `sym eod` exits non-zero only when a CRITICAL sym step (fill) fails."""
    proc = subprocess.run(
        [sys.executable, "-m", "sym.cli", "eod", "--as_of_date", end, "--steps", steps],
        cwd=str(repo_root()), capture_output=True, text=True, timeout=EOD_TIMEOUT_S,
    )
    context.log.info((proc.stdout or "")[-4000:])
    if proc.returncode != 0:
        context.log.error(f"sym eod --steps {steps} FAILED:\n{(proc.stderr or '')[-2000:]}")
        if critical:
            raise RuntimeError(f"`sym eod --steps {steps}` exited {proc.returncode}")


@op(retry_policy=_EOD_RETRY)
def resolve_eod_window(context, config: EodConfig) -> str:
    """Resolve the [start, end] window once (shared resolver) → ``"start/end"`` for every node."""
    start, end = resolve_window(context, config.start_date, config.end_date, config.as_of_date)
    context.log.info(f"eod window = {start}..{end}")
    return f"{start}/{end}"


# --- data-load phase: one op per bucket -------------------------------------------------------

# NOTE: op DEFINITION names are `eod_*`-prefixed so they don't collide with the same-named bucket jobs
# (op/graph/job names share one repository namespace — e.g. a bare `commodities` op clashes with the
# `commodities` job). The graph aliases each node back to the clean bucket name, so the UI still shows
# `equity_prices` / `fx` / `commodities` / ….
@op(name="eod_equity_prices", retry_policy=_EOD_RETRY)
def equity_prices_op(context, window: str) -> str:
    """Equity prices + identity + GICS classify — the sym-owned chain (monitor→fill→map→classify).
    CRITICAL: `fill` (the price pull) failing reddens the run and SKIPS the calc phase (returns derive
    from prices). Incremental-from-cursor → catches prices up THROUGH `end` (forward gap-fill; a
    historical re-pull is the `sym load --overwrite` runbook, not eod)."""
    _start, end = window.split("/")
    _sym_eod_steps(context, "monitor,fill,map,classify", end, critical=True)
    return window


@op(name="eod_fx", retry_policy=_EOD_RETRY)
def fx_op(context, window: str) -> str:
    """FX rates (USD base, incremental). Attempt-all (a failure is logged, doesn't gate returns)."""
    _start, end = window.split("/")
    _sym_eod_steps(context, "fx", end, critical=False)
    return window


@op(name="eod_index_levels", retry_policy=_EOD_RETRY)
def index_levels_op(context, window: str) -> str:
    """Index levels (benchmark registry). Attempt-all."""
    _start, end = window.split("/")
    _sym_eod_steps(context, "indices", end, critical=False)
    return window


def _make_bucket_op(key: str, doc: str):
    """A data-load op for a separate-package bucket — runs its shared builder commands, attempt-all
    (the builder's internal `validate "!"` critical markers are stripped so they can't red the night)."""
    @op(name=f"eod_{key}", retry_policy=_EOD_RETRY)
    def _op(context, window: str) -> str:
        start, end = window.split("/")
        cmds = list(_BUILDERS[key][0](start, end))
        if not cmds:
            context.log.warning(
                f"eod: bucket '{key}' produced NO commands (e.g. universe discovery empty) — "
                f"skipped, did not run. window={start}..{end}"
            )
            return window
        for cmd in cmds:
            raw = cmd[:-1] if cmd and cmd[-1] == "!" else cmd  # non-blocking in the EOD context
            _run_cmd(context, raw)
        return window

    _op.__doc__ = doc
    return _op


_BUCKET_OPS = {
    "rates": _make_bucket_op("rates", "Rates curves — BoE UK + world + validate. Attempt-all."),
    "commodities": _make_bucket_op("commodities", "Commodity front-month prices + validate. Attempt-all."),
    "macro": _make_bucket_op("macro", "Macro series. Attempt-all."),
    "alt_data": _make_bucket_op("alt_data", "Alt-data series. Attempt-all."),
    "fundamental": _make_bucket_op("fundamental", "Fundamentals snapshot. Attempt-all."),
    "universe": _make_bucket_op("universe", "Universe membership monitor. Attempt-all."),
}


@op
def data_complete(context, windows: list[str]) -> str:
    """Fan-in: returns the window once EVERY data node has completed, so the calc phase waits for the
    whole data-load phase. If a CRITICAL data node (equity_prices) failed, its output is missing and
    this op — and therefore the calc phase — is skipped. All nodes carry the same window string."""
    return windows[0] if windows else ""


# --- calculations phase -----------------------------------------------------------------------

@op(name="returns_recompute", retry_policy=_EOD_RETRY)
def recompute_op(context, window: str) -> str:
    """Recompute fact_returns (PR+TR) across [start, end] — range-native `sym recompute
    --start_date --end_date`. CRITICAL: a failure reddens the run and triggers the retry."""
    start, end = window.split("/")
    proc = subprocess.run(
        [sys.executable, "-m", "sym.cli", "recompute", "--start_date", start, "--end_date", end],
        cwd=str(repo_root()), capture_output=True, text=True, timeout=EOD_TIMEOUT_S,
    )
    context.log.info((proc.stdout or "")[-4000:])
    if proc.returncode != 0:
        context.log.error(f"sym recompute FAILED:\n{(proc.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym recompute` exited {proc.returncode} (critical)")
    return window


@op(name="validate", retry_policy=_EOD_RETRY)
def validate_op(context, window: str) -> None:
    """Cross-layer `validate` gate via `sym eod --steps validate` — which (by sym's doctrine) exits 0
    even when checks report FAIL, so a data-quality failure is LOGGED not run-red; the raise only fires
    if the validate STEP itself errors (exit non-zero)."""
    _start, end = window.split("/")
    _sym_eod_steps(context, "validate", end, critical=True)


# --- the two phase graphs + the job -----------------------------------------------------------

@graph
def eod_data() -> str:
    """DATA-LOAD phase — every bucket as its own node, all over the resolved window. Nodes are aliased
    to clean bucket names (the op definitions are `eod_*` to avoid job-name collisions)."""
    w = resolve_eod_window()
    outs = [
        equity_prices_op.alias("equity_prices")(w),
        fx_op.alias("fx")(w),
        index_levels_op.alias("index_levels")(w),
    ]
    outs += [_BUCKET_OPS[k].alias(k)(w) for k in _EOD_DATA_BUCKETS]
    return data_complete(outs)


@graph
def eod_calculations(window: str) -> None:
    """CALCULATIONS phase — recompute returns across the window, then validate."""
    validate_op(recompute_op(window))


@job(
    name="eod",
    description="Full end-of-day in one trigger over a [start_date, end_date] window (blank = today), as "
    "a readable DAG: the `eod_data` phase runs every bucket as its own node (equity_prices [+identity/"
    "classify], fx, index_levels, commodities, rates, macro, alt_data, fundamental, universe) and the "
    "`eod_calculations` phase (returns_recompute → validate) runs only after ALL data nodes finish. "
    "equity_prices is critical (its failure skips calc); the rest are attempt-all. Config (the window) "
    "is on the `resolve_eod_window` op. sym_eod / commodities + the per-asset bucket jobs remain for "
    "granular runs.",
)
def eod_job():
    eod_calculations(eod_data())


# Weekdays 18:30 America/New_York — after the US cash close, by which point EU/UK/Asia EOD series are
# also out. Timezone ALWAYS explicit (the hard requirement). STOPPED until enabled in the UI; this is
# the single schedule to enable for the whole nightly refresh (leave the per-asset ones stopped).
eod_daily = ScheduleDefinition(
    name="eod_daily",
    job=eod_job,
    cron_schedule="30 18 * * 1-5",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.STOPPED,
)
