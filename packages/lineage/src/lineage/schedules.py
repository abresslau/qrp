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


# ---- one `eod` job to run the whole end-of-day, split into two sequenced stages ----------
# eod_data (all the raw pulls) THEN eod_calculations (the derived returns), wired data -> calc so the
# calc stage runs ONLY after the data — including equity prices — is in (fact_returns derive from
# prices). One trigger; the two stages show in the run graph. Per-asset jobs remain for granular runs.


# The separate-package buckets the data stage runs AFTER the sym sequence — each via its bucket
# command builder (bucket_jobs._BUILDERS), so `eod` and the per-bucket jobs share ONE definition and
# can't drift. equity / index / fx / identity / classify come from the `sym eod` call (which keeps the
# monitor→fill→map→classify→indices→fx ordering); these six are the rest of the nine buckets.
_EOD_DATA_BUCKETS = ("rates", "commodities", "macro", "alt_data", "fundamental", "universe")


@op(retry_policy=RetryPolicy(max_retries=2, delay=300))
def eod_data(context, config: EodConfig) -> str:
    """STAGE 1 — pull every bucket's raw EOD data over the [start, end] window: the sym sequence
    (prices / identity / classify / index-levels / FX, MINUS recompute/validate which are the calc
    stage), then rates, commodities, macro, alt_data, fundamentals, and universe via their bucket
    command builders. Returns ``"start/end"`` so stage 2 recomputes the same window.

    The sym `fill` step is CRITICAL: if equity prices fail to pull, this op fails and the downstream
    calculations are skipped (returns derive from prices). The separate-package buckets are independent
    of equity returns — a failure there is logged but does NOT block the calc stage (attempt-all);
    their own internal `validate` critical-markers are downgraded to non-blocking in the EOD context."""
    root = str(repo_root())
    start, end = resolve_window(context, config.start_date, config.end_date, config.as_of_date)
    # 1. sym DATA steps only (recompute + validate are stage 2). `fill` is the critical equity-price
    #    pull and is incremental-from-cursor → it catches equity prices up THROUGH `end` (forward
    #    gap-fill). A historical re-pull of old prices is the `sym load --overwrite` runbook, not eod.
    sym = subprocess.run(
        [sys.executable, "-m", "sym.cli", "eod", "--as_of_date", end,
         "--steps", "monitor,fill,map,classify,indices,fx"],
        cwd=root, capture_output=True, text=True, timeout=7200,
    )
    context.log.info((sym.stdout or "")[-4000:])
    if sym.returncode != 0:
        context.log.error(f"sym eod data steps FAILED:\n{(sym.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym eod` data steps exited {sym.returncode} (critical: fill)")
    # 2. the separate-package buckets, over [start, end], via the shared builders — attempt-all
    #    (logged, non-blocking; they don't gate equity returns). A bucket's internal `validate` "!"
    #    marker is stripped here so a rates/commodity validate FAIL can't red the whole nightly run.
    for key in _EOD_DATA_BUCKETS:
        cmds = list(_BUILDERS[key][0](start, end))
        if not cmds:
            # A bucket that resolved to zero commands (e.g. `universe` when discovery returns []) must
            # be reported, not silently passed over — honest "no silent skip" (code-review finding).
            context.log.warning(
                f"eod_data: bucket '{key}' produced NO commands (e.g. universe discovery empty) — "
                f"skipped, did not run. window={start}..{end}"
            )
            continue
        for cmd in cmds:
            raw = cmd[:-1] if cmd and cmd[-1] == "!" else cmd  # non-blocking in the EOD context
            _run_cmd(context, raw)
    return f"{start}/{end}"


@op(retry_policy=RetryPolicy(max_retries=2, delay=300))
def eod_calculations(context, window: str) -> None:
    """STAGE 2 — runs once eod_data succeeds (equity prices are in). Recomputes fact_returns (PR+TR)
    across the SAME [start, end] window the data stage pulled (range-native `sym recompute
    --start_date --end_date`), then the cross-layer `validate` gate. recompute is critical — its
    failure turns the run red and triggers the retry. validate runs via `sym eod --steps validate`,
    which (by sym's doctrine) exits 0 even when checks report FAIL — so a data-quality failure is
    logged, not run-red; the raise here only fires if the validate STEP itself errors (exit non-zero)."""
    root = str(repo_root())
    start, end = window.split("/")
    rc = subprocess.run(
        [sys.executable, "-m", "sym.cli", "recompute", "--start_date", start, "--end_date", end],
        cwd=root, capture_output=True, text=True, timeout=7200,
    )
    context.log.info((rc.stdout or "")[-4000:])
    if rc.returncode != 0:
        context.log.error(f"sym recompute FAILED:\n{(rc.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym recompute` exited {rc.returncode} (critical)")
    val = subprocess.run(
        [sys.executable, "-m", "sym.cli", "eod", "--as_of_date", end, "--steps", "validate"],
        cwd=root, capture_output=True, text=True, timeout=7200,
    )
    context.log.info((val.stdout or "")[-4000:])
    if val.returncode != 0:
        context.log.error(f"sym validate FAILED:\n{(val.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym eod` validate step exited {val.returncode} (critical)")


@job(
    name="eod",
    description="Full end-of-day in one trigger over a [start_date, end_date] window (blank = today), "
    "in two sequenced stages: eod_data (ALL nine buckets — sym prices/identity/classify/index-levels/FX "
    "via `sym eod`, then rates, commodities, macro, alt_data, fundamentals, universe via their bucket "
    "builders) THEN eod_calculations (fact_returns PR+TR recomputed across the window + validate), which "
    "runs only after the data — incl. equity prices — is in. sym_eod / commodities + the per-asset "
    "bucket jobs (rates_load, …) remain for granular runs.",
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
