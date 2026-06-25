"""Constrained-solver + loop-closing tests (Story Q7.3/Q7.4/Q9.4) — fake conns, no DB."""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from optimiser.engine import (
    _const_corr_shrinkage,
    _pgd,
    _project_capped_simplex,
    _project_simplex,
    _tilt_scores,
    solve,
)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _RoutedConn:
    def __init__(self, routes=()):
        self._routes = list(routes)
        self.calls: list[tuple[str, tuple]] = []
        self.autocommit = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        for needle, cur in self._routes:
            if needle in sql:
                return cur
        return _Cur(one=(None,), rows=[])

    def cursor(self):
        outer = self

        class _Cu:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def executemany(self, sql, rows):
                outer.calls.append((sql, tuple(rows)))

        return _Cu()


# ---- capped-simplex projection ------------------------------------------------------------


def test_capped_projection_respects_mass_and_bounds():
    w = _project_capped_simplex([0.9, 0.5, 0.1, -0.2], cap=0.4)
    assert sum(w) == pytest.approx(1.0)
    assert all(-1e-12 <= x <= 0.4 + 1e-12 for x in w)


def test_capped_projection_equals_plain_simplex_when_cap_inactive():
    v = [0.3, 0.2, 0.1, 0.05]
    assert _project_capped_simplex(v, cap=1.0) == pytest.approx(_project_simplex(v))


def test_capped_projection_exact_full_cap():
    # cap*n == 1: the only feasible point is everyone AT the cap
    w = _project_capped_simplex([5.0, -3.0, 0.0, 1.0], cap=0.25)
    assert w == pytest.approx([0.25, 0.25, 0.25, 0.25])


def test_pgd_respects_the_cap_at_the_solution():
    # one dominant low-variance asset would take ~all weight unconstrained
    cov = [[0.0001, 0.0, 0.0], [0.0, 0.04, 0.0], [0.0, 0.0, 0.04]]
    mean = [0.0, 0.0, 0.0]
    w_free = _pgd(cov, mean, lam=1e6)
    assert w_free[0] > 0.9  # sanity: unconstrained min-var concentrates
    w_cap = _pgd(cov, mean, lam=1e6, cap=0.5)
    assert max(w_cap) <= 0.5 + 1e-9
    assert sum(w_cap) == pytest.approx(1.0)


# ---- Ledoit-Wolf constant-correlation covariance shrinkage --------------------------------


def _lcg_series(n, t, seed=1):
    """Deterministic series: a shared market factor + per-name idiosyncratic noise, so the
    return matrix has genuine (non-trivial) cross-correlations to shrink."""
    state = seed & 0x7FFFFFFF

    def rnd():
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF - 0.5

    mkt = [rnd() * 0.02 for _ in range(t)]
    return [[(0.5 + 0.2 * i) * mkt[k] + rnd() * 0.01 for k in range(t)] for i in range(n)]


def _is_pd(m) -> bool:
    """Pure-Python Cholesky — returns False if `m` is not positive-definite."""
    n = len(m)
    low = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            acc = sum(low[i][k] * low[j][k] for k in range(j))
            if i == j:
                d = m[i][i] - acc
                if d <= 1e-15:
                    return False
                low[i][j] = math.sqrt(d)
            else:
                low[i][j] = (m[i][j] - acc) / low[j][j]
    return True


def test_shrinkage_intensity_in_unit_interval_and_diagonal_preserved():
    mat = _lcg_series(6, 90)
    cov, delta = _const_corr_shrinkage(mat)
    assert 0.0 <= delta <= 1.0
    # symmetric
    assert all(cov[i][j] == pytest.approx(cov[j][i]) for i in range(6) for j in range(6))
    # diagonal == 1/t sample variance (the const-corr target leaves variances untouched)
    t = len(mat[0])
    for i in range(6):
        m = sum(mat[i]) / t
        var_mle = sum((x - m) ** 2 for x in mat[i]) / t
        assert cov[i][i] == pytest.approx(var_mle, rel=1e-9)


def test_shrinkage_is_positive_definite_even_when_sample_is_singular():
    # n > t: the sample covariance is rank-deficient (singular) — MVO's nightmare. The shrunk
    # estimate must still be PD (the headline Ledoit-Wolf guarantee, and the whole point here).
    mat = _lcg_series(8, 5)
    cov, delta = _const_corr_shrinkage(mat)
    assert delta > 0.0  # with t<n the optimal intensity must pull hard toward the target
    assert _is_pd(cov)


def test_shrinkage_grows_when_data_is_scarcer():
    # less data (smaller t) ⇒ noisier sample ⇒ more shrinkage toward the structured target.
    _, delta_short = _const_corr_shrinkage(_lcg_series(6, 25, seed=7))
    _, delta_long = _const_corr_shrinkage(_lcg_series(6, 400, seed=7))
    assert delta_short > delta_long


def test_solve_rejects_unknown_cov_method():
    sym, opt = _RoutedConn(), _RoutedConn()
    assert "unknown cov_method" in solve(sym, opt, u_conn=sym, eq_conn=sym, cov_method="kalman")["error"]


def test_solve_shrinkage_is_the_default_and_is_recorded(monkeypatch):
    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
        ("security_symbology", _Cur(rows=[])),
    ])
    opt = _RoutedConn([("INSERT INTO optimiser.solution", _Cur(one=(77,)))])
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200)  # no cov_method given → default
    assert out.get("solution_id") == 77, out.get("error")
    assert out["spec"]["cov_method"] == "shrinkage"
    assert out["summary"]["shrink_delta"] is not None
    assert 0.0 <= out["summary"]["shrink_delta"] <= 1.0


# ---- signal tilt ---------------------------------------------------------------------------


def test_tilt_scores_oriented_and_neutral_for_unscored(monkeypatch):
    import optimiser.engine as eng

    # direction 'low': a LOWER raw is favourable -> its z must come out POSITIVE
    monkeypatch.setattr(eng, "raw_factor",
                        lambda key, members, d, **kw: {"A": 1.0, "B": 3.0})
    monkeypatch.setattr(eng, "factor_direction", lambda key: "low")
    z, n_scored = _tilt_scores("vol_1y", ["A", "B", "C"], date(2026, 6, 5),
                               sym_conn=_RoutedConn(), eq_conn=_RoutedConn())
    assert n_scored == 2
    assert z[0] > 0 > z[1]  # A (low raw) favourable, B punished
    assert z[2] == 0.0  # unscored name: NEUTRAL, never fabricated


def test_tilt_shifts_weight_toward_the_favourable_name():
    cov = [[0.02, 0.0], [0.0, 0.02]]  # symmetric: untilted solution is 50/50
    mean = [0.0, 0.0]
    base = _pgd(cov, mean, lam=10)
    assert base[0] == pytest.approx(0.5, abs=1e-3)
    # closed form (KKT): w0 - w1 = (tilt0 - tilt1)/(2·lam·sigma²) = 0.1/0.4 = 0.25
    tilted = _pgd(cov, mean, lam=10, tilt=[0.05, -0.05])
    assert tilted[0] == pytest.approx(0.625, abs=0.005)  # 0.5 + 0.25/2 — solver hits KKT


# ---- solve-level validation + spec/holdout --------------------------------------------------


def test_solve_rejects_infeasible_cap_and_bad_tilt():
    sym, opt = _RoutedConn(), _RoutedConn()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, max_weight=0.01, n=40)  # 0.01*40 = 0.4 < 1
    assert "infeasible max_weight" in out["error"]
    sym, opt = _RoutedConn(), _RoutedConn()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, signal_tilt={"factor": "", "strength": 1.0})
    assert "signal_tilt needs" in out["error"]
    sym, opt = _RoutedConn(), _RoutedConn()
    assert "unknown method" in solve(sym, opt, u_conn=sym, eq_conn=sym, method="alchemy")["error"]
    # a tilt under min_variance would be numerically annihilated by lam=1e6 — refused
    sym, opt = _RoutedConn(), _RoutedConn()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, method="min_variance",
                signal_tilt={"factor": "mom_12_1", "strength": 1.0})
    assert "not meaningful under min_variance" in out["error"]


def _market_fixture(n_names=6, n_days=120):
    figis = [f"FIGI_{i:08d}" for i in range(n_names)]
    base = date(2026, 1, 1)
    rows = []
    for k in range(n_days):
        d = date.fromordinal(base.toordinal() + k)
        for i, f in enumerate(figis):
            # deterministic, varied series: small alternating returns per name
            rows.append((d, f, ((-1) ** (k + i)) * 0.001 * (i + 1)))
    return figis, rows


def test_solve_holdout_split_excludes_tail_from_training_and_scores_it(monkeypatch):
    import optimiser.engine as eng

    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
        ("security_symbology", _Cur(rows=[])),
    ])
    opt = _RoutedConn([("INSERT INTO optimiser.solution", _Cur(one=(42,)))])

    scored: list[tuple] = []

    def fake_score(conn, weights, start, end):
        scored.append((dict(weights), start, end))
        return {"total_return": 0.01, "ann_return": 0.02, "ann_vol": 0.1,
                "sharpe": 0.2, "max_drawdown": -0.05, "n_days": 63}

    monkeypatch.setattr(eng, "score_weights", fake_score)
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200, holdout_days=63)
    assert out.get("solution_id") == 42, out.get("error")
    # the spec records the TRAIN window: its end strictly precedes the holdout start
    train_end = date.fromisoformat(out["spec"]["train_end"])
    holdout_start = date.fromisoformat(out["holdout"]["start_date"])
    assert train_end < holdout_start  # no look-ahead into the score
    assert out["holdout"]["n_aligned_days"] == 63
    # both the candidate AND the equal-weight baseline were scored on the SAME window
    assert len(scored) == 2
    for _w, start, end in scored:
        assert start == train_end
        assert end == date.fromisoformat(out["holdout"]["end_date"])


def test_solve_persists_the_full_spec_to_sql():
    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
        ("security_symbology", _Cur(rows=[])),
    ])
    opt = _RoutedConn([("INSERT INTO optimiser.solution", _Cur(one=(7,)))])
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, universe_id="sp500", method="min_variance", n=6, lookback=200,
                max_weight=0.3)
    assert out.get("solution_id") == 7, out.get("error")
    insert = next(p for sql, p in opt.calls
                  if not isinstance(p, tuple) or "INSERT INTO optimiser.solution" in sql)
    spec = json.loads(insert[-1])  # spec is the last param
    assert spec["max_weight"] == 0.3
    assert spec["method"] == "min_variance"
    assert spec["signal_tilt"] is None
    assert spec["train_start"] is not None and spec["train_end"] is not None
    # the persisted solution respects the cap
    assert out["summary"]["max_weight"] <= 0.3 + 1e-9


def test_solve_holdout_too_large_is_a_named_error():
    figis, ret_rows = _market_fixture(n_days=80)
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
    ])
    opt = _RoutedConn()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200, holdout_days=70)  # 80 - 70 < 30
    assert "leaves <30 training days" in out["error"]


def test_solve_saves_portfolio_via_the_owning_writer(monkeypatch):
    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
        ("security_symbology", _Cur(rows=[])),
    ])
    opt = _RoutedConn([("INSERT INTO optimiser.solution", _Cur(one=(9,)))])

    class _PgwSpy:
        def __init__(self):
            self.created = None
            self.uploaded = None

        def create(self, name, client, ccy):
            self.created = (name, client, ccy)
            return 55

        def upload_weights(self, pid, as_of_date, items):
            self.uploaded = (pid, as_of_date, list(items))
            return {"stored": len(items)}

    spy = _PgwSpy()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200, portfolios_gw=spy)
    assert out["portfolio_id"] == 55
    assert spy.created[1] == "(optimiser)"
    pid, as_of, items = spy.uploaded
    assert pid == 55
    assert as_of == date.fromisoformat(out["spec"]["train_end"])  # the covariance end date
    assert sum(w for _f, w in items) == pytest.approx(1.0, abs=1e-3)


def test_cap_revalidated_against_surviving_names(monkeypatch):

    # request n=40 with a 5% cap (feasible) but only 6 names survive alignment:
    # cap*6 = 0.3 < 1 must be a NAMED error, never a sub-unit weight vector
    figis, ret_rows = _market_fixture(n_names=6)
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
    ])
    opt = _RoutedConn()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=40, lookback=200, max_weight=0.05)
    assert "surviving alignment" in out["error"]


def test_tilt_that_cannot_apply_is_an_error_not_a_silent_noop(monkeypatch):
    import optimiser.engine as eng

    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
    ])
    opt = _RoutedConn()
    # the factor scores only ONE of the selected names -> tilt cannot apply
    monkeypatch.setattr(eng, "raw_factor", lambda key, members, d, **kw: {figis[0]: 1.0})
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200, method="max_sharpe",
                signal_tilt={"factor": "mom_12_1", "strength": 1.0})
    assert "tilt cannot apply" in out["error"]
    assert "scored only 1" in out["error"]


def test_save_portfolio_failure_is_attributed_not_fatal():
    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
        ("security_symbology", _Cur(rows=[])),
    ])
    opt = _RoutedConn([("INSERT INTO optimiser.solution", _Cur(one=(11,)))])

    class _BrokenPgw:
        def create(self, *a):
            raise RuntimeError("portfolios db is down")

    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200, portfolios_gw=_BrokenPgw())
    assert out["solution_id"] == 11  # the committed solution still stands
    assert "portfolios db is down" in out["portfolio_error"]
    assert out["portfolio_id"] is None


def test_saved_portfolio_weights_are_renormalised():
    figis, ret_rows = _market_fixture()
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f,) for f in figis])),
        ("fundamentals", _Cur(rows=[(f,) for f in figis])),
        ("fact_returns", _Cur(rows=ret_rows)),
        ("security_symbology", _Cur(rows=[])),
    ])
    opt = _RoutedConn([("INSERT INTO optimiser.solution", _Cur(one=(12,)))])

    class _PgwSpy:
        def __init__(self):
            self.uploaded = None

        def create(self, *a):
            return 66

        def upload_weights(self, pid, as_of_date, items):
            self.uploaded = list(items)
            return {"stored": len(items), "unresolved": []}

    spy = _PgwSpy()
    out = solve(sym, opt, u_conn=sym, eq_conn=sym, n=6, lookback=200, portfolios_gw=spy)
    assert out["portfolio_id"] == 66
    assert sum(w for _f, w in spy.uploaded) == pytest.approx(1.0)  # full holding stated
    assert out["portfolio_upload"] == {"stored": len(spy.uploaded), "unresolved": []}


def test_router_422s_for_caller_shape_errors():
    from fastapi import HTTPException

    from optimiser.router import OptSolveRequest, solve_ep

    class _GwNeverReached:
        def solve(self, *a, **k):
            raise AssertionError("the 422 must fire before the gateway")

    with pytest.raises(HTTPException) as e:
        solve_ep(OptSolveRequest(method="alchemy"), _GwNeverReached())
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        solve_ep(OptSolveRequest(max_weight=0.01, n=40), _GwNeverReached())
    assert e.value.status_code == 422
    assert "infeasible" in e.value.detail
    with pytest.raises(HTTPException) as e:
        solve_ep(OptSolveRequest(signal_tilt={"factor": "nope", "strength": 1.0}),
                 _GwNeverReached())
    assert e.value.status_code == 422
