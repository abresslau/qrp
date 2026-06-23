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

from .sym_run import repo_root


class EodConfig(Config):
    """Run-time config for the EOD op.

    ``as_of_date`` (YYYY-MM-DD) is the business date to run the pipeline for. Left blank it
    defaults to today (resolved at run time) — so scheduled ticks and a plain manual launch run
    for today. Set it in the Dagster launchpad to re-run any past date; CLI: ``sym eod --as_of_date``.
    """

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
def rates_curve_load(context) -> None:
    """Load BoE UK yield curves then validate (rates owns its steps; trigger-only here).

    Manual: ``uv run rates curve load`` then ``uv run rates validate``. The load tails the
    latest BoE bundle (gating a desynced current-day publish); validate runs the reconciliation
    + stale guards. A FAIL in validate (exit 2) turns the run red and triggers the retry.
    """
    root = str(repo_root())
    load = subprocess.run(
        [sys.executable, "-m", "rates.cli", "curve", "load"],
        cwd=root, capture_output=True, text=True, timeout=3600,
    )
    context.log.info((load.stdout or "")[-4000:])
    if load.returncode != 0:
        context.log.error(f"rates curve load FAILED (exit {load.returncode}):\n{(load.stderr or '')[-2000:]}")
        raise RuntimeError(f"`rates curve load` exited {load.returncode}")
    val = subprocess.run(
        [sys.executable, "-m", "rates.cli", "validate"],
        cwd=root, capture_output=True, text=True, timeout=600,
    )
    context.log.info((val.stdout or "")[-4000:])
    if val.returncode != 0:
        raise RuntimeError(f"`rates validate` exited {val.returncode} (a curve check FAILED)")


@job(
    name="rates_uk_boe",
    description="UK (Bank of England) yield curve — daily load + validate. GB ONLY (all other "
    "countries are in `rates_world`); the BoE is a separate, richer fetch (full gilt nominal/real/"
    "implied-inflation + OIS). For everything in one run use the `rates` bucket. "
    "Manual: `uv run rates curve load`.",
)
def rates_curve_job():
    rates_curve_load()


# Weekdays 17:15 Europe/London — after BoE's daily yield-curve publish (London time, DST-aware).
# Timezone is ALWAYS set explicitly (the hard requirement for every schedule). STOPPED until enabled.
rates_curve_daily = ScheduleDefinition(
    name="rates_uk_boe_daily",
    job=rates_curve_job,
    cron_schedule="15 17 * * 1-5",
    execution_timezone="Europe/London",
    default_status=DefaultScheduleStatus.STOPPED,
)


@op(retry_policy=RetryPolicy(max_retries=2, delay=300))
def rates_world_load(context) -> None:
    """Tail-load every FX-matrix country's curve (euro area by member) then validate.

    Manual: ``uv run rates curve load-world`` then ``uv run rates validate``. Each source returns its
    full published history; we pass a short ``--start_date`` window (last ~12 days) so the daily tick
    is a light idempotent top-up (equal-value rows skip), not a full re-pull. The driver is
    attempt-all: a single source failing is logged and skipped, so the op only goes red if validate
    FAILs (exit 2). GB stays on ``rates_curve_daily`` (the BoE archive is a separate fetch)."""
    root = str(repo_root())
    scheduled = getattr(context, "run", None)
    tick = (scheduled.tags.get("dagster/scheduled_execution_time") if scheduled else None)
    end = (tick or "")[:10] or date.today().isoformat()
    start = (date.fromisoformat(end) - timedelta(days=12)).isoformat()
    load = subprocess.run(
        [sys.executable, "-m", "rates.cli", "curve", "load-world",
         "--start_date", start, "--end_date", end],
        cwd=root, capture_output=True, text=True, timeout=5400,
    )
    context.log.info((load.stdout or "")[-6000:])
    if load.returncode != 0:
        context.log.error(
            f"rates load-world FAILED (exit {load.returncode}):\n{(load.stderr or '')[-2000:]}")
        raise RuntimeError(f"`rates curve load-world` exited {load.returncode}")
    val = subprocess.run(
        [sys.executable, "-m", "rates.cli", "validate"],
        cwd=root, capture_output=True, text=True, timeout=900,
    )
    context.log.info((val.stdout or "")[-6000:])
    if val.returncode != 0:
        raise RuntimeError(f"`rates validate` exited {val.returncode} (a curve check FAILED)")


@job(
    name="rates_world",
    description="World yield curves (ex-UK) — tail load + validate for every FX-matrix country "
    "from its central bank (euro area by member). UK is in `rates_uk_boe`; for everything in one "
    "run use the `rates` bucket. Manual: `uv run rates curve load-world`.",
)
def rates_world_job():
    rates_world_load()


# Weekdays 18:30 America/New_York — after the US Treasury par-curve publish and the US cash close,
# by which point the day's EU/UK/Asia EOD series are also out (Asia is the prior session, fine for
# daily EOD curves). Timezone ALWAYS explicit (the hard requirement). STOPPED until enabled in the UI.
rates_world_daily = ScheduleDefinition(
    name="rates_world_daily",
    job=rates_world_job,
    cron_schedule="30 18 * * 1-5",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.STOPPED,
)
