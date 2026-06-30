"""The composite `eod` job — a FLAT readable DAG: per-bucket data nodes + per-PRODUCT calculations.

The point of the structure: each calculation runs as soon as ITS OWN data is in (equity_prices ->
equity_returns / equity_gics), NOT after a global data barrier; `validate` is the cross-layer gate that
fans in from every leaf. These tests pin the per-bucket decomposition, the per-product calc chains, the
"no global barrier" property (equity calcs depend on equity_prices only), and clean repo registration."""

from __future__ import annotations


def _deps_of(graph, alias):
    """The input-name -> dependency map for the node invoked as `alias` in `graph`."""
    for inv, inputs in graph.dependencies.items():
        if inv.alias == alias:
            return inputs
    raise AssertionError(f"no node aliased {alias!r}")


def _upstreams(graph, alias):
    """Set of node names feeding the node aliased `alias` (flattening any fan-in list input)."""
    def nodes(x):
        if hasattr(x, "node"):
            return [x.node]
        if isinstance(x, (list, tuple)):
            return [n for e in x for n in nodes(e)]
        return []

    return set(nodes(list(_deps_of(graph, alias).values())))


def test_eod_job_is_flat_with_one_node_per_bucket():
    from lineage.schedules import eod_job

    assert eod_job.name == "eod"
    assert {n.name for n in eod_job.graph.nodes} == {
        "date_range",
        "equity_prices", "fx", "index_levels", "rates", "commodities",
        "macro", "alt_data", "fundamental", "universe",      # data nodes
        "equity_returns", "equity_gics", "index_returns",    # per-product calcs
        "validate",                                          # cross-layer gate
    }


def test_per_product_calcs_depend_only_on_their_own_data_no_global_barrier():
    # the headline property: each calc runs as soon as ITS data lands — equity calcs off equity_prices,
    # index_returns off index_levels — NOT after fx / macro / universe / … (no global data barrier).
    from lineage.schedules import eod_job

    assert _upstreams(eod_job.graph, "equity_returns") == {"equity_prices"}
    assert _upstreams(eod_job.graph, "equity_gics") == {"equity_prices"}
    assert _upstreams(eod_job.graph, "index_returns") == {"index_levels"}


def test_data_nodes_only_depend_on_the_window_resolver():
    # every raw-data node hangs off date_range alone (so they all run in parallel).
    from lineage.schedules import eod_job

    for node in ("equity_prices", "fx", "index_levels", "rates", "commodities",
                 "macro", "alt_data", "fundamental", "universe"):
        assert _upstreams(eod_job.graph, node) == {"date_range"}, node


def test_validate_fans_in_from_every_leaf():
    # validate is cross-layer: it runs only after the equity calcs AND every data leaf.
    from lineage.schedules import eod_job

    assert _upstreams(eod_job.graph, "validate") == {
        "equity_returns", "equity_gics", "index_returns", "fx",
        "rates", "commodities", "macro", "alt_data", "fundamental", "universe",
    }


def test_eod_data_covers_all_separate_package_buckets():
    # AC#1: the four buckets the old eod NEVER ran (macro, alt_data, fundamental, universe) plus rates
    # and commodities are all data nodes built from the shared _BUILDERS (single source of truth).
    from lineage.bucket_jobs import _BUILDERS
    from lineage.schedules import _EOD_DATA_BUCKETS

    assert set(_EOD_DATA_BUCKETS) == {
        "rates", "commodities", "macro", "alt_data", "fundamental", "universe"
    }
    for key in _EOD_DATA_BUCKETS:
        assert key in _BUILDERS and _BUILDERS[key][0] is not None


def test_equity_returns_windows_the_recompute(monkeypatch):
    import lineage.schedules as sched
    from dagster import build_op_context

    calls = []

    class _P:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(sched.subprocess, "run", lambda args, **kw: (calls.append(args) or _P()))
    out = sched.equity_returns_op(build_op_context(), "2026-06-23/2026-06-29")
    assert out == "2026-06-23/2026-06-29"  # passes the window through to validate's fan-in
    recompute = next(a for a in calls if "recompute" in a)
    assert "--start_date" in recompute and "2026-06-23" in recompute
    assert "--end_date" in recompute and "2026-06-29" in recompute


def test_critical_vs_attempt_all(monkeypatch):
    import lineage.schedules as sched
    from dagster import build_op_context

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(sched.subprocess, "run", lambda args, **kw: _Fail())
    import pytest

    # critical: equity_prices (fill) and equity_returns (recompute) raise on failure
    with pytest.raises(RuntimeError):
        sched.equity_prices_op(build_op_context(), "2026-06-23/2026-06-29")
    with pytest.raises(RuntimeError):
        sched.equity_returns_op(build_op_context(), "2026-06-23/2026-06-29")

    # attempt-all: equity_gics (classify) and a separate-package bucket op must NOT raise on failure
    sched.equity_gics_op(build_op_context(), "2026-06-23/2026-06-29")
    sched._BUCKET_OPS["fundamental"](build_op_context(), "2026-06-23/2026-06-29")


def test_repository_builds_without_name_conflicts():
    # Build the FULL repository (what `dagster dev`'s code server does) — a plain import does NOT
    # trigger op/graph/job name-uniqueness validation, so this is the guard that catches a collision
    # (e.g. an eod bucket op named `commodities` clashing with the `commodities` job).
    import lineage.definitions as d

    repo = d.defs.get_repository_def()
    job_names = {j.name for j in repo.get_all_jobs()}
    assert {"eod", "commodities"}.issubset(job_names)  # both load, no conflict


def test_eod_registered_in_definitions():
    import lineage.definitions as d

    sched_names = {s.name for s in d.defs.schedules}
    assert "eod_daily" in sched_names
    from lineage.schedules import eod_daily

    assert eod_daily.execution_timezone  # the hard requirement: explicit tz, never the UTC default
