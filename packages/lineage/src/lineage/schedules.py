"""A daily schedule for sym's end-of-day pipeline — Dagster as a *trigger + observer only*.

Deliberately minimal: Dagster does NOT model the EOD steps as a workflow. ``sym`` already owns the
daily sequence (monitor → fill → map → classify → benchmarks → fx → recompute → validate); this fires the
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
from datetime import date

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
    benchmarks / validate) still exit 0 by sym's design ("a hiccup shouldn't fail the night"), so
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
