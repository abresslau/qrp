"""The composite `eod` job — a readable DAG: two phase graphs (eod_data -> eod_calculations), with
one node per bucket inside the data phase and recompute -> validate inside the calc phase.

The load-bearing invariant is the PHASE EDGE — the calculations phase runs AFTER the whole data phase
(fact_returns derive from equity prices), never in parallel. These tests pin the phase split, the
per-bucket node decomposition (so the UI shows fx / equity / commodities / … separately), and that the
job is registered for the UI."""

from __future__ import annotations


def test_eod_job_has_two_phase_graphs():
    from lineage.schedules import eod_job

    assert eod_job.name == "eod"
    # the job's top level is the two phase sub-graphs
    assert {n.name for n in eod_job.graph.nodes} == {"eod_data", "eod_calculations"}


def test_calculations_phase_depends_on_data_phase_not_parallel():
    from lineage.schedules import eod_job

    deps = eod_job.graph.dependencies
    calc_dep = next(inputs for inv, inputs in deps.items() if inv.alias == "eod_calculations")
    assert "window" in calc_dep  # calc phase takes the window the data phase produced
    assert calc_dep["window"].node == "eod_data"  # ... so it runs AFTER the whole data phase
    data_dep = next(inputs for inv, inputs in deps.items() if inv.alias == "eod_data")
    assert data_dep == {}  # data phase is the root


def test_data_phase_has_one_node_per_bucket():
    # The whole point of the refactor: every bucket is its own visible node in the data-load phase
    # (plus the window resolver and the fan-in), so the UI shows fx / equity / commodities / … apart.
    from lineage.schedules import eod_data

    nodes = {n.name for n in eod_data.nodes}
    assert {
        "equity_prices", "fx", "index_levels",          # sym-owned nodes
        "rates", "commodities", "macro", "alt_data", "fundamental", "universe",  # bucket nodes
        "resolve_eod_window", "data_complete",          # window resolve + fan-in
    } == nodes


def test_calc_phase_is_recompute_then_validate():
    from lineage.schedules import eod_calculations

    nodes = {n.name for n in eod_calculations.nodes}
    assert nodes == {"returns_recompute", "validate"}
    # validate depends on returns_recompute (recompute first)
    deps = eod_calculations.dependencies
    val_dep = next(inputs for inv, inputs in deps.items() if inv.alias == "validate")
    assert val_dep["window"].node == "returns_recompute"


def test_data_complete_fans_in_every_data_node():
    # the fan-in (which gates the calc phase) must depend on ALL nine bucket nodes — so a critical
    # equity_prices failure (its output missing) skips data_complete and therefore the calc phase.
    from lineage.schedules import eod_data

    deps = eod_data.dependencies
    dc_dep = next(inputs for inv, inputs in deps.items() if inv.alias == "data_complete")

    # the single List input fans in from all nine data nodes; flatten whatever nesting Dagster uses
    def _nodes(x):
        if hasattr(x, "node"):
            return [x.node]
        if isinstance(x, (list, tuple)):
            return [n for e in x for n in _nodes(e)]
        return []

    upstreams = set(_nodes(list(dc_dep.values())))
    assert {
        "equity_prices", "fx", "index_levels", "rates", "commodities",
        "macro", "alt_data", "fundamental", "universe",
    } == upstreams


def test_eod_data_covers_all_separate_package_buckets():
    # AC#1: the four buckets the old eod NEVER ran (macro, alt_data, fundamental, universe) plus rates
    # and commodities are all bucket nodes built from the shared _BUILDERS (single source of truth).
    from lineage.bucket_jobs import _BUILDERS
    from lineage.schedules import _EOD_DATA_BUCKETS

    assert set(_EOD_DATA_BUCKETS) == {
        "rates", "commodities", "macro", "alt_data", "fundamental", "universe"
    }
    for key in _EOD_DATA_BUCKETS:
        assert key in _BUILDERS and _BUILDERS[key][0] is not None


def test_recompute_op_windows_the_recompute(monkeypatch):
    # the calc recompute node must recompute returns over the SAME [start, end] the data phase produced.
    import lineage.schedules as sched
    from dagster import build_op_context

    calls = []

    class _P:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(sched.subprocess, "run", lambda args, **kw: (calls.append(args) or _P()))
    out = sched.recompute_op(build_op_context(), "2026-06-23/2026-06-29")
    assert out == "2026-06-23/2026-06-29"  # passes the window through to validate
    recompute = next(a for a in calls if "recompute" in a)
    assert "--start_date" in recompute and "2026-06-23" in recompute
    assert "--end_date" in recompute and "2026-06-29" in recompute


def test_equity_prices_is_critical_others_attempt_all(monkeypatch):
    # equity_prices raises on a sym-eod failure (critical → skips calc); a bucket op logs + continues.
    import lineage.schedules as sched
    from dagster import build_op_context

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(sched.subprocess, "run", lambda args, **kw: _Fail())
    import pytest

    with pytest.raises(RuntimeError):
        sched.equity_prices_op(build_op_context(), "2026-06-23/2026-06-29")  # critical → raises

    # a separate-package bucket op (fundamental) must NOT raise on a failing command (attempt-all)
    fundamental_op = sched._BUCKET_OPS["fundamental"]
    fundamental_op(build_op_context(), "2026-06-23/2026-06-29")  # must not raise


def test_eod_registered_in_definitions():
    import lineage.definitions as d  # must import clean (no duplicate job names)

    sched_names = {s.name for s in d.defs.schedules}
    assert "eod_daily" in sched_names
    from lineage.schedules import eod_daily

    assert eod_daily.execution_timezone  # the hard requirement: explicit tz, never the UTC default


def test_repository_builds_without_name_conflicts():
    # Build the FULL repository (what `dagster dev`'s code server does) — a plain import does NOT
    # trigger op/graph/job name-uniqueness validation, so this is the guard that catches a collision
    # (e.g. an eod bucket op named `commodities` clashing with the `commodities` job).
    import lineage.definitions as d

    repo = d.defs.get_repository_def()
    job_names = {j.name for j in repo.get_all_jobs()}
    assert {"eod", "commodities"}.issubset(job_names)  # both load, no conflict
