"""The nine **bucket jobs** — Dagster's trigger/backfill surface over the bucket taxonomy.

One job per bucket (``lineage.buckets.BUCKETS``). Each is a *trigger + observer* exactly like the
EOD/rates schedules: the op shells the SAME CLI an operator would type; Dagster only decides WHEN.

Config (launchpad):
* ``subcategories: list[str]`` — empty (default) runs the WHOLE bucket via its aggregate command(s);
  a non-empty list runs just those subcategories (one, several). Unknown values pass through to the
  CLI, which errors on a bad one (isolated per-subcategory, never aborts the rest).
* ``as_of_date: str`` — blank → today (the scheduled tick if launched by a schedule, else the wall
  clock); set → that business date, translated to the right ``--start_date/--end_date`` window per
  bucket.

Attempt-all: every command runs in its own try/except; a failure is logged (``[FAIL] …``) and the
run continues. The op only goes red when EVERY command failed (a wholly-broken bucket) or a
*critical* command (a ``validate``) failed — mirroring ``sym eod``'s "a hiccup shouldn't fail the
night, a critical step should".
"""

import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta

from dagster import Config, RetryPolicy, job, op
from pydantic import Field

from .buckets import BUCKETS
from .sym_run import repo_root

# A single command = (module, *args); run as ``python -m <module> <args>``. ``critical`` commands
# (validate) turn the run red on failure; the rest are attempt-all (logged, non-fatal).
Cmd = tuple[str, ...]
CMD_TIMEOUT_S = 5400


def _resolve_as_of(context, config_as_of: str) -> str:
    as_of = (config_as_of or "").strip()
    if as_of:
        return as_of
    run = getattr(context, "run", None)
    tick = (run.tags.get("dagster/scheduled_execution_time") if run else None) or ""
    return tick[:10] or date.today().isoformat()


def _window(as_of: str, days: int = 1) -> tuple[str, str]:
    """A short [start, end] window ending at ``as_of`` — a light idempotent top-up (matches the
    rates_world tail). days=1 → a single business day's worth of slack."""
    end = date.fromisoformat(as_of)
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def _discover_universes() -> list[str]:
    """Live universe ids via ``sym universe list`` (first token per row). Best-effort: [] on error."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "sym.cli", "universe", "list"],
            cwd=str(repo_root()), capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return []
        out = []
        for line in (proc.stdout or "").splitlines():
            tok = line.split()
            if tok and tok[0].isascii() and not line.startswith(" "):
                out.append(tok[0])
        return out
    except Exception:  # noqa: BLE001 — discovery is best-effort
        return []


# --- per-bucket command builders ------------------------------------------------------------
# all_cmds(as_of) -> the whole-bucket commands; one_cmds(subcat, as_of) -> a single subcategory.
# (module, *args, "!") — a trailing "!" marks the command critical (validate).

def _fx_all(a: str) -> list[Cmd]:
    return [("sym.cli", "fx", "load")]


def _equity_all(a: str) -> list[Cmd]:
    return [("sym.cli", "load")]  # incremental-from-cursor for every universe member


def _equity_one(u: str, a: str) -> list[Cmd]:
    s, e = _window(a)
    return [("sym.cli", "load", "--scope", f"universe:{u}", "--start_date", s, "--end_date", e)]


def _index_all(a: str) -> list[Cmd]:
    return [("sym.cli", "indices"), ("sym.cli", "msci-pull")]


def _index_one(p: str, a: str) -> list[Cmd]:
    return [("sym.cli", "msci-pull")] if p == "msci" else [("sym.cli", "indices")]


def _rates_all(a: str) -> list[Cmd]:
    s, e = _window(a, days=12)
    return [
        ("rates.cli", "curve", "load"),                                   # GB (BoE archive)
        ("rates.cli", "curve", "load-world", "--start_date", s, "--end_date", e),
        ("rates.cli", "validate", "!"),
    ]


def _rates_one(c: str, a: str) -> list[Cmd]:
    s, e = _window(a, days=12)
    if c.upper() == "GB":
        return [("rates.cli", "curve", "load"), ("rates.cli", "validate", "!")]
    return [
        ("rates.cli", "curve", "load-world", "--country", c, "--start_date", s, "--end_date", e),
        ("rates.cli", "validate", "!"),
    ]


def _fundamental_all(a: str) -> list[Cmd]:
    return [("sym.cli", "fundamentals", "--all")]


def _fundamental_one(u: str, a: str) -> list[Cmd]:
    return [("sym.cli", "fundamentals", "--universe", u)]


def _altdata_all(a: str) -> list[Cmd]:
    return [("altdata.ingest",)]


def _macro_all(a: str) -> list[Cmd]:
    return [("macro.ingest",)]


def _universe_all(a: str) -> list[Cmd]:
    return [("sym.cli", "universe", "monitor", u) for u in _discover_universes()]


def _universe_one(u: str, a: str) -> list[Cmd]:
    return [("sym.cli", "universe", "monitor", u)]


CALC_TYPES = ("returns", "gics", "index_returns")


def _calc_cmds(t: str, a: str) -> list[Cmd]:
    s, e = _window(a)
    # returns (recompute) is the CRITICAL compute step (trailing "!" → reddens the run on failure,
    # per the Dev Notes compute-vs-ingest rule) and is date-windowed so a backfill targets `as_of`.
    return {
        "returns": [("sym.cli", "recompute", "--start_date", s, "--end_date", e, "!")],
        "gics": [("sym.cli", "classify")],
        "index_returns": [("sym.cli", "indices")],
    }.get(t, [])


def _calc_all(a: str) -> list[Cmd]:
    return [c for t in CALC_TYPES for c in _calc_cmds(t, a)]


def _calc_one(t: str, a: str) -> list[Cmd]:
    return _calc_cmds(t, a)


# bucket key -> (all_cmds, one_cmds | None, discover | None)
_BUILDERS: dict[str, tuple[Callable, Callable | None, Callable | None]] = {
    "fx": (_fx_all, None, None),
    "equity_prices": (_equity_all, _equity_one, _discover_universes),
    "index_levels": (_index_all, _index_one, lambda: ["yahoo", "msci"]),
    "rates": (_rates_all, _rates_one, None),
    "fundamental": (_fundamental_all, _fundamental_one, _discover_universes),
    "alt_data": (_altdata_all, None, None),
    "macro": (_macro_all, None, None),
    "universe": (_universe_all, _universe_one, _discover_universes),
    "calculations": (_calc_all, _calc_one, lambda: list(CALC_TYPES)),
}


def _run_cmd(context, raw: Cmd) -> bool:
    """Run one ``python -m <module> <args>``; True on success. ``critical`` (trailing '!') re-raises."""
    critical = bool(raw) and raw[-1] == "!"
    parts = list(raw[:-1] if critical else raw)
    if not parts:  # defensive: a builder must never yield an empty command
        context.log.error("[FAIL] empty command tuple (builder bug) — skipping")
        return False
    module, args = parts[0], parts[1:]
    pretty = f"{module} " + " ".join(args)
    context.log.info(f"run: python -m {pretty}")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", module, *args],
            cwd=str(repo_root()), capture_output=True, text=True, timeout=CMD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        # A hung non-critical ingest must NOT take the whole run red (attempt-all): log + skip.
        # A critical step (validate/recompute) still propagates.
        context.log.error(f"[FAIL] {pretty}: timed out after {CMD_TIMEOUT_S}s")
        if critical:
            raise
        return False
    tail = (proc.stdout or "")[-3000:]
    if proc.returncode != 0:
        context.log.error(f"[FAIL] {pretty} (exit {proc.returncode}):\n{tail}\n{(proc.stderr or '')[-1500:]}")
        if critical:
            raise RuntimeError(f"critical step `{pretty}` exited {proc.returncode}")
        return False
    context.log.info(f"[ok] {pretty} ({round(time.monotonic() - started, 1)}s)\n{tail[-800:]}")
    return True


class BucketConfig(Config):
    subcategories: list[str] = Field(default_factory=list)
    as_of_date: str = ""


def _run_bucket(context, key: str, config: BucketConfig) -> None:
    all_cmds, one_cmds, discover = _BUILDERS[key]
    as_of = _resolve_as_of(context, config.as_of_date)
    # Validate the business date ONCE, up front — a malformed value (e.g. an operator typo) gets a
    # clear error instead of a stack trace from deep inside a window builder.
    try:
        date.fromisoformat(as_of)
    except ValueError as exc:
        raise RuntimeError(f"bucket '{key}': invalid as_of_date {as_of!r} (expected YYYY-MM-DD)") from exc
    subcats = [s.strip() for s in (config.subcategories or []) if s.strip()]

    # Fail-fast on an unknown subcategory (AC#2) where the bucket can enumerate its valid set.
    if subcats and discover is not None:
        valid = set(discover())
        unknown = [s for s in subcats if s not in valid]
        if valid and unknown:
            raise RuntimeError(
                f"bucket '{key}': unknown subcategor{'y' if len(unknown) == 1 else 'ies'} "
                f"{unknown}; valid: {sorted(valid)}"
            )

    if not subcats:
        plan: list[Cmd] = list(all_cmds(as_of))
        context.log.info(f"bucket '{key}': ALL subcategories, as_of={as_of} ({len(plan)} commands)")
        units = [("(all)", plan)]
    elif one_cmds is None:
        # single-subcategory bucket (fx/alt_data/macro) — the CLI has no per-subcategory selector,
        # so it runs the whole thing; be HONEST that the selection was not applied (don't silently
        # imply it was). [Review: macro/fx/alt_data selector deferral]
        context.log.warning(
            f"bucket '{key}': no per-subcategory selector for this source; selection {subcats} "
            f"NOT applied — running the whole bucket. as_of={as_of}"
        )
        units = [("(all)", list(all_cmds(as_of)))]
    else:
        context.log.info(f"bucket '{key}': {subcats}, as_of={as_of}")
        units = [(s, list(one_cmds(s, as_of))) for s in subcats]

    # An empty plan is NOT success — it means discovery returned nothing or a selection resolved to
    # no commands. Fail loudly instead of a green run that ingested zero rows. [Review]
    total = sum(len(cmds) for _, cmds in units)
    if total == 0:
        raise RuntimeError(
            f"bucket '{key}': nothing to run (no commands resolved for "
            f"{subcats or 'all'} — discovery empty or unsupported selection)"
        )

    ok = failed = 0
    for label, cmds in units:
        for cmd in cmds:
            if _run_cmd(context, cmd):  # critical failure raises inside (turns run red)
                ok += 1
            else:
                failed += 1
                context.log.warning(f"bucket '{key}' subcategory '{label}': a command failed (continuing)")
    context.log.info(f"bucket '{key}' done: {ok} ok, {failed} failed across {len(units)} subcategory unit(s)")
    if ok == 0 and failed > 0:
        raise RuntimeError(f"bucket '{key}': every command failed ({failed})")


def _make_job(b):
    @op(name=f"{b.key}_load", retry_policy=RetryPolicy(max_retries=2, delay=300))
    def _bucket_op(context, config: BucketConfig) -> None:
        _run_bucket(context, b.key, config)

    @job(
        name=b.key,
        description=f"{b.label} bucket — by {b.subcategory}. Empty subcategories = all; "
        f"set as_of_date for a backfill. Shells the sym/rates/macro/altdata CLI.",
    )
    def _bucket_job():
        _bucket_op()

    return _bucket_job


BUCKET_JOBS = [_make_job(b) for b in BUCKETS]
