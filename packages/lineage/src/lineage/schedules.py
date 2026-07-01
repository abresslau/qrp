"""The end-of-day Dagster jobs + schedules — trigger + observer only.

Dagster does NOT model the EOD steps as a workflow; every node shells the **exact same** CLI an
operator runs by hand, and Dagster only decides WHEN + retains the run log. This module defines:

* ``eod`` — the composite, all-packages end-of-day DAG (per-product nodes: equity/index/fx/commodity/
  rates/macro/alt_data/fundamental/universe + their calcs → validate), over a [start_date, end_date]
  window. The single job to run for the whole nightly refresh. Schedule ``eod_daily``.

**Manual running is unchanged** (no Dagster needed): ``uv run sym eod`` (sym's own pipeline),
``uv run commodity price load``, etc. Commodity has NO separate job/schedule — it is a node in the
``eod`` DAG (``commodity`` + ``commodity_returns``) and a granular ``commodity_load`` bucket job
(generated from ``bucket_jobs`` like every other data bucket) for ad-hoc runs. (The older sym-only
``sym_eod`` Dagster job was retired too — ``eod``'s sym-owned nodes cover the same steps.)
"""

import subprocess
import sys
from datetime import date

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


# NOTE: the standalone sym-only `sym_eod` Dagster job + `sym_eod_daily` schedule were RETIRED — the
# composite `eod` job's sym-owned nodes (equity_prices = monitor,fill,map; fx; index_levels;
# equity_gics = classify; equity_returns = recompute; validate) cover the same steps. The `sym eod`
# CLI those nodes shell is unchanged (still `uv run sym eod`).


# ---- `eod` as a readable DAG: per-bucket data nodes + per-PRODUCT calculations ----------------
# A FLAT job graph (NOT phase sub-graphs — those force the calc phase to wait for ALL data; the point
# here is that each calculation runs as soon as ITS OWN data is in). The window resolves once
# (`date_range`) and threads to every node as "start/end". Topology:
#
#   date_range ─► equity_prices ──► equity_returns ─────┐
#                 ├─► index_levels ──► index_returns ────┤
#                 ├─► commodity ──► commodity_returns ───┤
#                 ├─► equity_gics ───────────────────────┤─► validate   (cross-layer gate)
#                 ├─► fx ────────────────────────────────┤
#                 └─► rates, macro, alt_data, ───────────┘
#                     fundamental, universe
#
# A calculation that DERIVES from a product's data chains off it: equity_returns (`sym recompute`)
# after equity_prices; index_returns (`indices returns`) after index_levels; commodity_returns
# (`commodity returns` — trailing-window returns over the raw continuous settle, roll jumps included)
# after commodity. equity_gics (`sym classify`) does NOT derive from prices — it classifies the
# current security set — so it runs independently off the window. fx / rates / macro / alt_data /
# fundamental / universe are data-only
# (analytics are derive-on-read). `validate` checks the whole warehouse, so it fans in from every leaf
# (the per-product calcs + the data-only nodes). op tags mark `phase: data|calc` for legibility. op
# DEFINITION names are `eod_*`-prefixed
# (op/graph/job names share one repo namespace — a bare `commodity` op clashes with the `commodity`
# job); nodes are aliased to clean names for the UI. Config (the window) is on `date_range`.

_EOD_DATA_BUCKETS = ("rates", "commodity", "macro", "alt_data", "fundamental", "universe")
_DATA_TAG = {"phase": "data"}
_CALC_TAG = {"phase": "calc"}
# Per-op subprocess cap. 1h comfortably covers a wide backfill (a week of equity fill is ~minutes; the
# slowest data op, `fundamentals --all`, is attempt-all so a timeout there is caught, not fatal) while
# capping a hung vendor socket at 1h instead of 2h. (Ops finding: a stalled yfinance call on a delisted
# ticker blocked equity_prices for the full old 7200s cap; the old 2 retries could stack it toward ~6h.)
EOD_TIMEOUT_S = 3600
# Data ops hit vendors — a hung/failed pull must NOT be retried (a retry just re-hangs); surface it fast.
_DATA_RETRY = RetryPolicy(max_retries=0)
# Calc / critical ops — one quick retry covers a transient DB-lock / network blip.
_CALC_RETRY = RetryPolicy(max_retries=1, delay=60)


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


def _shell(context, label: str, args: list[str], *, critical: bool) -> None:
    """Run ``python -m <args>``; attempt-all (log + swallow) unless ``critical`` (raise on non-zero)."""
    proc = subprocess.run(
        [sys.executable, "-m", *args], cwd=str(repo_root()),
        capture_output=True, text=True, timeout=EOD_TIMEOUT_S,
    )
    context.log.info(f"{label}: " + (proc.stdout or "")[-4000:])
    if proc.returncode != 0:
        context.log.error(f"{label} FAILED (exit {proc.returncode}):\n{(proc.stderr or '')[-2000:]}")
        if critical:
            raise RuntimeError(f"`{label}` exited {proc.returncode}")


@op(name="date_range", retry_policy=_CALC_RETRY)
def date_range_op(context, config: EodConfig) -> str:
    """Resolve the [start, end] date range once (shared resolver) → ``"start/end"`` for every node.
    This is the `date_range` node — config (start_date/end_date/as_of_date) lives here."""
    start, end = resolve_window(context, config.start_date, config.end_date, config.as_of_date)
    context.log.info(f"eod date range = {start}..{end}")
    return f"{start}/{end}"


# --- DATA nodes (op defs `eod_*`-prefixed to avoid job-name collisions; aliased to clean UI names) ---

@op(name="eod_equity_prices", retry_policy=_DATA_RETRY, tags=_DATA_TAG)
def equity_prices_op(context, window: str) -> str:
    """Equity prices + identity — the sym-owned chain (monitor→fill→map). CRITICAL: `fill` (the price
    pull) failing reddens the run and SKIPS the equity calcs + validate (returns derive from prices).
    Incremental-from-cursor → catches prices up THROUGH `end` (forward gap-fill; a historical re-pull is
    the `sym load --overwrite` runbook, not eod). GICS classify is now its own calc node (equity_gics)."""
    _start, end = window.split("/")
    _sym_eod_steps(context, "monitor,fill,map", end, critical=True)
    return window


@op(name="eod_fx", retry_policy=_DATA_RETRY, tags=_DATA_TAG)
def fx_op(context, window: str) -> str:
    """FX rates (USD base, incremental). Attempt-all (a failure is logged, doesn't gate returns)."""
    _start, end = window.split("/")
    _sym_eod_steps(context, "fx", end, critical=False)
    return window


@op(name="eod_index_levels", retry_policy=_DATA_RETRY, tags=_DATA_TAG)
def index_levels_op(context, window: str) -> str:
    """Index LEVELS (Yahoo) + universe links + FIGIs — NO returns recompute (that's the `index_returns`
    calc node). Attempt-all."""
    _shell(context, "indices levels", ["indices.cli", "levels"], critical=False)
    return window


def _make_bucket_op(key: str, doc: str):
    """A data node for a separate-package bucket — runs its shared builder commands, attempt-all
    (the builder's internal `validate "!"` critical markers are stripped so they can't red the night)."""
    @op(name=f"eod_{key}", retry_policy=_DATA_RETRY, tags=_DATA_TAG)
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
    "commodity": _make_bucket_op("commodity", "Commodity front-month prices + validate. Attempt-all."),
    "macro": _make_bucket_op("macro", "Macro series. Attempt-all."),
    "alt_data": _make_bucket_op("alt_data", "Alt-data series. Attempt-all."),
    "fundamental": _make_bucket_op("fundamental", "Fundamentals snapshot. Attempt-all."),
    "universe": _make_bucket_op("universe", "Universe membership monitor. Attempt-all."),
}


# --- EQUITY calculations — depend ONLY on equity_prices, so they start as soon as equity data lands ---

@op(name="eod_equity_returns", retry_policy=_CALC_RETRY, tags=_CALC_TAG)
def equity_returns_op(context, window: str) -> str:
    """EQUITY calc — recompute fact_returns (PR+TR) across [start, end] (range-native `sym recompute`).
    Runs right after `equity_prices` (NOT after the other buckets). CRITICAL: a failure reddens the run,
    triggers the retry, and skips `validate`."""
    start, end = window.split("/")
    _shell(context, f"sym recompute {start}..{end}",
           ["sym.cli", "recompute", "--start_date", start, "--end_date", end], critical=True)
    return window


@op(name="eod_equity_gics", retry_policy=_CALC_RETRY, tags=_CALC_TAG)
def equity_gics_op(context, window: str) -> str:
    """GICS classification (`sym classify`) — classifies the current security set; does NOT depend on
    equity prices (or the day's price load), so it runs independently off the window. Attempt-all
    (classify is non-critical — a failure is logged, doesn't gate validate)."""
    _shell(context, "sym classify", ["sym.cli", "classify"], critical=False)
    return window


@op(name="eod_index_returns", retry_policy=_CALC_RETRY, tags=_CALC_TAG)
def index_returns_op(context, window: str) -> str:
    """INDEX calc — recompute index returns (fact_index_returns) across [start, end], derived from the
    index levels. Runs right after `index_levels` (mirrors equity's prices -> returns split). Attempt-all
    (a hiccup here is logged, doesn't gate validate; index returns are a secondary product)."""
    start, end = window.split("/")
    _shell(context, f"indices returns {start}..{end}",
           ["indices.cli", "returns", "--start_date", start, "--end_date", end], critical=False)
    return window


@op(name="eod_commodity_returns", retry_policy=_CALC_RETRY, tags=_CALC_TAG)
def commodity_returns_op(context, window: str) -> str:
    """COMMODITY calc — recompute trailing-window returns (commodity.return_daily) across [start, end]
    from the settle series. Runs right after `commodity` (mirrors equity/index). Attempt-all (a hiccup
    is logged, doesn't gate validate). NB: raw continuous front-month — returns include roll jumps."""
    start, end = window.split("/")
    _shell(context, f"commodity returns {start}..{end}",
           ["commodity.cli", "returns", "--start_date", start, "--end_date", end], critical=False)
    return window


# --- cross-layer validate — fans in from EVERY leaf (runs after all data + the equity calcs) ----------

@op(name="validate", retry_policy=_CALC_RETRY, tags=_CALC_TAG)
def validate_op(context, windows: list[str]) -> None:
    """Cross-layer `validate` gate via `sym eod --steps validate`. Fans in from every leaf node, so it
    runs only after all data + the equity calcs are in. Exits 0 even when checks report FAIL (sym's
    doctrine) — a data-quality failure is LOGGED not run-red; the raise only fires if the validate STEP
    itself errors. Skipped if a critical node (equity_prices/equity_returns) failed (its output missing)."""
    win = windows[0] if windows else ""
    end = win.split("/")[1] if "/" in win else date.today().isoformat()
    _sym_eod_steps(context, "validate", end, critical=True)


@job(
    name="eod",
    description="Full end-of-day in one trigger over a [start_date, end_date] window (blank = today), as "
    "a readable DAG. DATA nodes (equity_prices, fx, index_levels, commodity, rates, macro, alt_data, "
    "fundamental, universe) load off the resolved window; PER-PRODUCT CALCS run as soon as their own data "
    "lands — equity_prices → equity_returns (recompute) + equity_gics (classify); index_levels → "
    "index_returns; `validate` is the cross-layer gate that fans in from every leaf. equity_prices + equity_returns are "
    "critical (a failure skips validate); the rest are attempt-all. Config (the window) is on the "
    "`date_range` op. sym_eod / commodity + the per-asset bucket jobs remain for granular runs.",
)
def eod_job():
    w = date_range_op()  # the `date_range` node — resolves [start, end] for every downstream node
    eq = equity_prices_op.alias("equity_prices")(w)
    idx = index_levels_op.alias("index_levels")(w)
    comm = _BUCKET_OPS["commodity"].alias("commodity")(w)
    leaves = [
        equity_returns_op.alias("equity_returns")(eq),    # returns DERIVE from prices → after equity_prices
        equity_gics_op.alias("equity_gics")(w),           # GICS is independent of prices → off date_range
        index_returns_op.alias("index_returns")(idx),     # index calc — right after index levels
        commodity_returns_op.alias("commodity_returns")(comm),  # commodity calc — right after commodity data
        fx_op.alias("fx")(w),
    ]
    # the remaining data-only buckets (commodity is wired above for its returns calc)
    leaves += [_BUCKET_OPS[k].alias(k)(w) for k in _EOD_DATA_BUCKETS if k != "commodity"]
    validate_op.alias("validate")(leaves)  # cross-layer gate — fans in from every leaf


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
