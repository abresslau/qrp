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
    assert "as_of_date" in calc_dep  # calc takes the date the data stage resolved
    assert calc_dep["as_of_date"].node == "eod_data"  # ... and therefore runs AFTER eod_data
    # eod_data is a root (no upstream) — it runs first
    data_dep = next(inputs for inv, inputs in deps.items() if inv.alias == "eod_data")
    assert data_dep == {}


def test_eod_registered_in_definitions():
    import lineage.definitions as d  # must import clean (no duplicate job names)

    sched_names = {s.name for s in d.defs.schedules}
    assert "eod_daily" in sched_names
    from lineage.schedules import eod_daily

    assert eod_daily.execution_timezone  # the hard requirement: explicit tz, never the UTC default
