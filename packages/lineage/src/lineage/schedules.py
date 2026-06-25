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


@op(retry_policy=RetryPolicy(max_retries=2, delay=300))
def eod_data(context, config: EodConfig) -> str:
    """STAGE 1 — pull every asset class's raw EOD data: sym prices/identity/classify/index-levels/FX
    (the `sym eod` sequence MINUS recompute/validate, which are the calc stage), then rates (BoE UK +
    world curves) and commodities. Returns the resolved as_of_date so stage 2 runs for the same day.

    The sym `fill` step is CRITICAL: if equity prices fail to pull, this op fails and the downstream
    calculations are skipped (returns derive from prices). rates/commodities are independent of equity
    returns — a failure there is logged but does NOT block the calc stage (attempt-all)."""
    root = str(repo_root())
    as_of = config.as_of_date.strip()
    if not as_of:
        scheduled = getattr(context, "run", None)
        tick = (scheduled.tags.get("dagster/scheduled_execution_time") if scheduled else None)
        as_of = (tick or "")[:10] or date.today().isoformat()
    # 1. sym DATA steps only (recompute + validate are stage 2). fill is the critical equity-price pull.
    sym = subprocess.run(
        [sys.executable, "-m", "sym.cli", "eod", "--as_of_date", as_of,
         "--steps", "monitor,fill,map,classify,indices,fx"],
        cwd=root, capture_output=True, text=True, timeout=7200,
    )
    context.log.info((sym.stdout or "")[-4000:])
    if sym.returncode != 0:
        context.log.error(f"sym eod data steps FAILED:\n{(sym.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym eod` data steps exited {sym.returncode} (critical: fill)")
    # 2. rates + commodities — attempt-all (logged, non-blocking; they don't gate equity returns).
    win_start = (date.fromisoformat(as_of) - timedelta(days=12)).isoformat()
    for label, cmd in (
        ("rates_uk", ["rates.cli", "curve", "load"]),
        ("rates_world", ["rates.cli", "curve", "load-world", "--start_date", win_start,
                         "--end_date", as_of]),
        ("commodities", ["commodity.cli", "price", "load", "--start_date", win_start,
                         "--end_date", as_of]),
    ):
        p = subprocess.run([sys.executable, "-m", *cmd], cwd=root,
                           capture_output=True, text=True, timeout=5400)
        context.log.info(f"{label}: {(p.stdout or '')[-1500:]}")
        if p.returncode != 0:
            context.log.error(f"{label} FAILED (logged, non-blocking):\n{(p.stderr or '')[-1500:]}")
    return as_of


@op(retry_policy=RetryPolicy(max_retries=2, delay=300))
def eod_calculations(context, as_of_date: str) -> None:
    """STAGE 2 — runs once eod_data succeeds (equity prices are in). Materialises fact_returns (PR+TR)
    via the sym `recompute` step, then the cross-layer `validate` gate, for the SAME as_of_date the
    data stage pulled. recompute is critical — its failure turns the run red and triggers the retry."""
    root = str(repo_root())
    proc = subprocess.run(
        [sys.executable, "-m", "sym.cli", "eod", "--as_of_date", as_of_date,
         "--steps", "recompute,validate"],
        cwd=root, capture_output=True, text=True, timeout=7200,
    )
    context.log.info((proc.stdout or "")[-4000:])
    if proc.returncode != 0:
        context.log.error(f"sym eod recompute/validate FAILED:\n{(proc.stderr or '')[-2000:]}")
        raise RuntimeError(f"`sym eod` calc steps exited {proc.returncode} (critical: recompute)")


@job(
    name="eod",
    description="Full end-of-day in one trigger, in two sequenced stages: eod_data (sym prices / "
    "identity / classify / index levels / FX + rates UK/world + commodities) THEN eod_calculations "
    "(fact_returns PR+TR + validate), which runs only after the data — incl. equity prices — is in. "
    "sym_eod / commodities + the per-asset bucket jobs (rates_load, …) remain for granular runs.",
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
