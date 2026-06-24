"""Parameter-grid sweeps with overfitting statistics (Story 1B).

A single backtest can't know how many siblings were tried, so its Sharpe says nothing about
selection bias. A SWEEP runs the SAME base strategy across a grid of parameter variations, then
evaluates the whole set together: the Deflated Sharpe of the best config (benchmarked against the
expected-max-Sharpe of N=grid-size trials), the Probability of Backtest Overfitting (PBO via CSCV),
and the Minimum Backtest Length the trial count demands. N is taken as the full grid size — a
conservative count (correlated configs only raise the hurdle), with a cluster-based effective-N a
ledgered refinement.

Each grid point is a normal persisted ``backtest.run`` (so it shows in the runs list), linked back
to the sweep via ``run.sweep_id``. The sweep row holds the verdict.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics as st

import psycopg

from . import stats
from .engine import run_backtest

# Parameters a sweep is allowed to vary / fix. Anything in run_backtest's spec.
_RUN_KWARGS = {"factor", "universe_id", "top_pct", "top_n", "weighting", "rebalance",
               "cost_bps", "start_date", "end_date"}


def _annualised_em(n_trials: int, sigma_sr: float) -> float:
    return stats.expected_max_sharpe(n_trials, sigma_sr) * math.sqrt(252)


def run_sweep(
    sym_conn: psycopg.Connection,
    bt_conn: psycopg.Connection,
    *,
    base_spec: dict,
    grid: dict,
    n_splits: int = 16,
    alt_conn: psycopg.Connection | None = None,
    macro_conn: psycopg.Connection | None = None,
) -> dict:
    """Run one backtest per grid point and evaluate the set for overfitting.

    ``base_spec`` = fixed run kwargs (e.g. factor, universe_id, dates, cost_bps). ``grid`` =
    ``{param: [values, ...]}``; the cartesian product is the config set (N trials). Persists a
    ``backtest.sweep`` row with the DSR/PBO/MinBTL verdict and links each run to it.
    """
    bad = (set(base_spec) | set(grid)) - _RUN_KWARGS
    if bad:
        return {"error": f"unknown sweep parameter(s): {sorted(bad)}; "
                         f"allowed: {sorted(_RUN_KWARGS)}"}
    if not grid:
        return {"error": "a sweep needs a grid that varies at least one parameter"}
    keys = list(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    if len(combos) < 2:
        return {"error": "a sweep needs >= 2 configurations (the grid must vary something)"}

    bt_conn.autocommit = True
    runs: list[dict] = []
    for vals in combos:
        spec = {**base_spec, **dict(zip(keys, vals, strict=True))}
        try:
            res = run_backtest(sym_conn, bt_conn, return_daily=True,
                               alt_conn=alt_conn, macro_conn=macro_conn, **spec)
        except Exception as exc:  # noqa: BLE001 — attempt-all: one bad config must not abort the
            # sweep and orphan the runs already committed (autocommit) under no sweep_id.
            res = {"error": f"{type(exc).__name__}: {exc}"}
        runs.append({"config": dict(zip(keys, vals, strict=True)), "result": res})

    ok = [r for r in runs if "daily" in r["result"]]
    if len(ok) < 2:
        errs = [r["result"].get("error") for r in runs if "error" in r["result"]]
        return {"error": "fewer than 2 configs produced a runnable backtest",
                "config_errors": errs[:10]}

    # Align all configs on their COMMON trading days (coverage gates can shift each config's start).
    date_sets = [set(d for d, _ in r["result"]["daily"]) for r in ok]
    common = sorted(set.intersection(*date_sets))
    if len(common) < 2 * n_splits:
        return {"error": f"only {len(common)} common days across configs — too few for "
                         f"n_splits={n_splits} (need >= {2 * n_splits})"}
    aligned = [[dict(r["result"]["daily"])[d] for d in common] for r in ok]

    n_trials = len(combos)  # N = full grid size — the multiple-testing count (conservative)
    sharpes = [stats.sharpe(s) for s in aligned]
    sigma_sr = st.pstdev(sharpes) if len(sharpes) > 1 else 0.0
    best_i = max(range(len(ok)), key=lambda i: sharpes[i])
    best = ok[best_i]

    dsr = stats.deflated_sharpe(aligned[best_i], n_trials, sigma_sr)
    pbo_res = stats.pbo(aligned, n_splits=n_splits)
    em_ann = _annualised_em(n_trials, sigma_sr)
    min_btl = stats.min_backtest_length_years(n_trials, em_ann)
    actual_years = (
        (_iso_days(common[-1]) - _iso_days(common[0])) / 365.25 if len(common) > 1 else 0.0
    )

    summary = {
        "n_configs": n_trials,
        "n_runnable": len(ok),
        "n_common_days": len(common),
        "actual_years": actual_years,
        "sigma_sr": sigma_sr,
        "deflated_sharpe": dsr,                       # {dsr, sharpe, sr_benchmark, ...} of the best
        "pbo": pbo_res,                               # {pbo, n_splits, n_combos, median_logit}
        "min_btl_years": min_btl,
        "min_btl_satisfied": (min_btl is not None and actual_years >= min_btl),
        "best": {
            "config": best["config"],
            "run_id": best["result"].get("run_id"),
            "sharpe_ann": dsr["sharpe_ann"],
        },
        # verdict: credible only if the best config's DSR clears 0.95 AND PBO is acceptable
        "verdict_credible": (
            dsr["dsr"] is not None and dsr["dsr"] > 0.95
            and pbo_res is not None and pbo_res["pbo"] is not None and pbo_res["pbo"] <= 0.05
        ),
    }

    run_ids = [r["result"]["run_id"] for r in ok if r["result"].get("run_id")]
    sweep_id = _persist(bt_conn, base_spec, grid, n_trials, best["result"].get("run_id"),
                        summary, run_ids)

    return {"sweep_id": sweep_id, "base_spec": base_spec, "grid": grid,
            "n_configs": n_trials, "summary": summary,
            "config_errors": [r["result"]["error"] for r in runs if "error" in r["result"]]}


def _iso_days(iso: str):
    from datetime import date
    return date.fromisoformat(iso).toordinal()


def _persist(bt_conn, base_spec, grid, n_configs, best_run_id, summary, run_ids) -> int | None:
    """Insert the sweep row and link its runs. Best-effort: returns None if the sweep schema
    isn't deployed yet (the per-config runs still persisted independently)."""
    try:
        with bt_conn.transaction():
            sweep_id = bt_conn.execute(
                """
                INSERT INTO backtest.sweep (base_spec, grid, n_configs, best_run_id, summary)
                VALUES (%s::jsonb, %s::jsonb, %s, %s, %s::jsonb) RETURNING sweep_id
                """,
                (json.dumps(base_spec, default=str), json.dumps(grid, default=str),
                 n_configs, best_run_id, json.dumps(summary, default=str)),
            ).fetchone()[0]
            if run_ids:
                bt_conn.execute(
                    "UPDATE backtest.run SET sweep_id = %s WHERE run_id = ANY(%s)",
                    (sweep_id, run_ids),
                )
        return int(sweep_id)
    except psycopg.errors.UndefinedTable:
        return None


if __name__ == "__main__":
    from backtest.db import connect

    sym_conn = connect("sym")
    bt_conn = connect()
    try:
        out = run_sweep(
            sym_conn, bt_conn,
            base_spec={"factor": "mom_12_1", "universe_id": "sp500"},
            grid={"top_pct": [0.1, 0.2, 0.3], "rebalance": ["monthly", "quarterly"]},
        )
        print(json.dumps(out, indent=2, default=str))
    finally:
        sym_conn.close()
        bt_conn.close()
