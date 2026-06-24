"""Sweep orchestration tests (Story 1B) — fake conns + monkeypatched engine, no DB."""

from __future__ import annotations

import json
import math

import backtest.sweep as sweep_mod
from backtest.sweep import run_sweep


class _Cur:
    def __init__(self, one=None):
        self._one = one

    def fetchone(self):
        return self._one


class _SweepConn:
    """Captures INSERT/UPDATE; yields a sweep_id; supports transaction()/autocommit."""

    def __init__(self, sweep_id=42):
        self._sweep_id = sweep_id
        self.calls: list[tuple] = []
        self.autocommit = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "INSERT INTO backtest.sweep" in sql:
            return _Cur(one=(self._sweep_id,))
        return _Cur(one=(None,))

    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()


def _fake_run_factory():
    """A fake run_backtest: deterministic per-config daily series over a shared date grid, so
    configs align on a common date set and have distinct, reproducible Sharpes."""
    counter = {"n": 0}
    DATES = [f"2026-{(i // 21) + 1:02d}-{(i % 21) + 1:02d}" for i in range(120)]

    def fake(sym_conn, bt_conn, *, return_daily=False, alt_conn=None, macro_conn=None, **spec):
        counter["n"] += 1
        rid = counter["n"]
        # series mean keyed by the config's top_pct so configs genuinely differ
        seed = int(round((spec.get("top_pct") or 0.2) * 100)) + hash(spec.get("rebalance", "")) % 7
        st = seed & 0x7FFFFFFF
        daily = []
        for d in DATES:
            st = (1103515245 * st + 12345) & 0x7FFFFFFF
            r = (st / 0x7FFFFFFF - 0.5) * 0.02 + 0.0002 * (seed % 5)
            daily.append([d, r])
        out = {"run_id": rid, "summary": {"strategy": {"sharpe": 1.0}}, "spec": spec}
        if return_daily:
            out["daily"] = daily
        return out

    return fake


def test_rejects_unknown_params_and_thin_grid(monkeypatch):
    monkeypatch.setattr(sweep_mod, "run_backtest", _fake_run_factory())
    sym, bt = object(), _SweepConn()
    assert "unknown sweep parameter" in run_sweep(
        sym, bt, base_spec={"factor": "mom_12_1"}, grid={"bogus": [1, 2]})["error"]
    # a grid with a single config isn't a sweep
    assert ">= 2 configurations" in run_sweep(
        sym, bt, base_spec={"factor": "mom_12_1"}, grid={"top_pct": [0.2]})["error"]


def test_sweep_computes_and_persists_the_verdict(monkeypatch):
    monkeypatch.setattr(sweep_mod, "run_backtest", _fake_run_factory())
    sym, bt = object(), _SweepConn(sweep_id=99)
    out = run_sweep(
        sym, bt,
        base_spec={"factor": "mom_12_1", "universe_id": "sp500"},
        grid={"top_pct": [0.1, 0.2, 0.3], "rebalance": ["monthly", "quarterly"]},
        n_splits=8,
    )
    assert out.get("sweep_id") == 99, out.get("error")
    assert out["n_configs"] == 6  # 3 × 2 cartesian product
    s = out["summary"]
    # the multiple-testing count is the full grid size
    assert s["n_configs"] == 6
    assert s["deflated_sharpe"]["n_trials"] == 6
    assert s["deflated_sharpe"]["dsr"] is not None
    assert 0.0 <= s["pbo"]["pbo"] <= 1.0
    assert s["best"]["run_id"] is not None
    assert isinstance(s["verdict_credible"], bool)
    # MinBTL present and the satisfied-flag is internally consistent
    if s["min_btl_years"] is not None:
        assert s["min_btl_satisfied"] == (s["actual_years"] >= s["min_btl_years"])


def test_sweep_persists_row_and_links_runs(monkeypatch):
    monkeypatch.setattr(sweep_mod, "run_backtest", _fake_run_factory())
    sym, bt = object(), _SweepConn(sweep_id=7)
    run_sweep(sym, bt, base_spec={"factor": "mom_12_1"},
              grid={"top_pct": [0.1, 0.2, 0.3]}, n_splits=8)
    inserts = [c for c in bt.calls if "INSERT INTO backtest.sweep" in c[0]]
    updates = [c for c in bt.calls if "UPDATE backtest.run SET sweep_id" in c[0]]
    assert len(inserts) == 1
    # n_configs persisted = grid size; base_spec + grid round-trip as JSON
    params = inserts[0][1]
    assert params[2] == 3  # n_configs
    assert json.loads(params[1]) == {"top_pct": [0.1, 0.2, 0.3]}  # grid jsonb
    assert len(updates) == 1  # the runs got linked to the sweep
    assert updates[0][1][0] == 7  # sweep_id bound first


def test_sweep_survives_missing_schema(monkeypatch):
    # if backtest.sweep isn't deployed yet, persistence degrades to sweep_id=None, not a crash
    import psycopg

    monkeypatch.setattr(sweep_mod, "run_backtest", _fake_run_factory())

    class _NoTableConn(_SweepConn):
        def execute(self, sql, params=None):
            if "INSERT INTO backtest.sweep" in sql:
                raise psycopg.errors.UndefinedTable("relation backtest.sweep does not exist")
            return super().execute(sql, params)

    out = run_sweep(object(), _NoTableConn(), base_spec={"factor": "mom_12_1"},
                    grid={"top_pct": [0.1, 0.2, 0.3]}, n_splits=8)
    assert out["sweep_id"] is None  # attributed, not fatal
    assert out["summary"]["deflated_sharpe"]["dsr"] is not None  # the stats still computed


def test_min_btl_uses_annualised_expected_max(monkeypatch):
    # guard the annualisation: MinBTL must use E[max SR]·√252, not the per-day figure
    monkeypatch.setattr(sweep_mod, "run_backtest", _fake_run_factory())
    out = run_sweep(object(), _SweepConn(), base_spec={"factor": "mom_12_1"},
                    grid={"top_pct": [0.1, 0.2, 0.3, 0.4]}, n_splits=8)
    s = out["summary"]
    if s["min_btl_years"] is not None and s["sigma_sr"] > 0:
        from backtest.stats import expected_max_sharpe
        em_ann = expected_max_sharpe(4, s["sigma_sr"]) * math.sqrt(252)
        assert s["min_btl_years"] == (2 * math.log(4) / em_ann**2)
