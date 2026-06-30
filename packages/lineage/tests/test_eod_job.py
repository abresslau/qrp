"""The composite `eod` job: one trigger, two sequenced stages (eod_data -> eod_calculations).

The load-bearing invariant is the DEPENDENCY EDGE — calculations must run AFTER the data pull
(fact_returns derive from equity prices), never in parallel. These tests pin that so a future
refactor can't silently un-sequence them, and confirm the job is registered for the UI."""

from __future__ import annotations


def test_eod_job_has_data_then_calculations_stages():
    from lineage.schedules import eod_job

    assert eod_job.name == "eod"
    ops = {n.name for n in eod_job.graph.nodes}
    assert ops == {"eod_data", "eod_calculations"}


def test_calculations_depends_on_data_not_parallel():
    from lineage.schedules import eod_job

    deps = eod_job.graph.dependencies
    # find the eod_calculations node's input dependency
    calc_dep = next(
        inputs for inv, inputs in deps.items() if inv.alias == "eod_calculations"
    )
    assert "window" in calc_dep  # calc takes the [start, end] window the data stage resolved
    assert calc_dep["window"].node == "eod_data"  # ... and therefore runs AFTER eod_data
    # eod_data is a root (no upstream) — it runs first
    data_dep = next(inputs for inv, inputs in deps.items() if inv.alias == "eod_data")
    assert data_dep == {}


def test_eod_data_covers_all_separate_package_buckets():
    # AC#1: the four buckets the old eod NEVER ran (macro, alt_data, fundamental, universe) plus rates
    # and commodities are all in the data stage's fan-out (equity/index/fx come via the `sym eod` call).
    from lineage.schedules import _EOD_DATA_BUCKETS

    assert set(_EOD_DATA_BUCKETS) == {
        "rates", "commodities", "macro", "alt_data", "fundamental", "universe"
    }
    # every fan-out bucket has a command builder (single source of truth with the per-bucket jobs)
    from lineage.bucket_jobs import _BUILDERS

    for key in _EOD_DATA_BUCKETS:
        assert key in _BUILDERS and _BUILDERS[key][0] is not None


def test_eod_calculations_recomputes_the_window(monkeypatch):
    # Stage 2 must recompute returns over the SAME [start, end] the data stage returned ("start/end").
    import lineage.schedules as sched
    from dagster import build_op_context

    calls = []

    class _P:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(sched.subprocess, "run", lambda args, **kw: (calls.append(args) or _P()))
    sched.eod_calculations(build_op_context(), "2026-06-23/2026-06-29")
    recompute = next(a for a in calls if "recompute" in a)
    assert "--start_date" in recompute and "2026-06-23" in recompute
    assert "--end_date" in recompute and "2026-06-29" in recompute


def test_eod_registered_in_definitions():
    import lineage.definitions as d  # must import clean (no duplicate job names)

    sched_names = {s.name for s in d.defs.schedules}
    assert "eod_daily" in sched_names
    from lineage.schedules import eod_daily

    assert eod_daily.execution_timezone  # the hard requirement: explicit tz, never the UTC default
