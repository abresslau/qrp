"""Strategy-spec engine tests (Story Q6.3 + Q9.4) — fake conns, no network/DB."""

from __future__ import annotations

from datetime import date

import pytest

from backtest.engine import (
    _cap_weights,
    _daily_weighted,
    _rebalance_dates,
    _select_top,
    run_backtest,
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
        return _Cur(one=(None, None), rows=[])


# ---- rebalance cadence -------------------------------------------------------------------

_DAYS = [
    date(2026, 1, 2), date(2026, 1, 15),
    date(2026, 2, 2), date(2026, 3, 2),
    date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1),
    date(2026, 7, 1), date(2026, 10, 1),
]


def test_rebalance_dates_monthly_first_trading_day():
    out = _rebalance_dates(_DAYS, "monthly")
    assert out == [date(2026, 1, 2), date(2026, 2, 2), date(2026, 3, 2), date(2026, 4, 1),
                   date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1), date(2026, 10, 1)]


def test_rebalance_dates_quarterly_first_trading_day_of_quarter():
    out = _rebalance_dates(_DAYS, "quarterly")
    # Q1 starts at the first trading day in Jan; Q2 at Apr 1; Q3 Jul 1; Q4 Oct 1
    assert out == [date(2026, 1, 2), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)]


# ---- selection ---------------------------------------------------------------------------

_RAW = {"A": 3.0, "B": 2.0, "C": 1.0, "D": 0.5, "E": 0.1}


def test_select_top_n_takes_exactly_n_by_direction():
    assert _select_top(_RAW, "high", None, 2) == ["A", "B"]
    assert _select_top(_RAW, "low", None, 2) == ["E", "D"]
    assert _select_top(_RAW, "high", None, 99) == ["A", "B", "C", "D", "E"]  # capped at len


def test_select_top_pct_unchanged_behavior():
    assert _select_top(_RAW, "high", 0.4, None) == ["A", "B"]
    assert _select_top(_RAW, "high", 0.01, None) == ["A"]  # ceil floor of 1


# ---- cap weighting -----------------------------------------------------------------------


def test_cap_weights_proportional_and_drops_capless_names_counted():
    # the seam's size factor returns mcaps; one name has none ON/before d -> dropped + counted
    conn = _RoutedConn([
        ("fundamentals", _Cur(rows=[("FIGI_BIG00000", 300e9), ("FIGI_SML00000", 100e9)])),
    ])
    weights, dropped = _cap_weights(conn, ["FIGI_BIG00000", "FIGI_SML00000", "FIGI_NOCAP00"],
                                    date(2026, 6, 1))
    assert dropped == 1  # honest count, never silently zero-weighted
    assert weights["FIGI_BIG00000"] == pytest.approx(0.75)
    assert weights["FIGI_SML00000"] == pytest.approx(0.25)
    assert "FIGI_NOCAP00" not in weights


# ---- weighted daily series ---------------------------------------------------------------


def test_daily_weighted_uses_fixed_weights_renormalised_over_priced():
    conn = _RoutedConn([
        ("fact_returns", _Cur(rows=[
            (date(2026, 6, 2), "FIGI_A0000000", 0.01),
            (date(2026, 6, 2), "FIGI_B0000000", 0.03),
            (date(2026, 6, 3), "FIGI_A0000000", 0.02),  # B unpriced: renormalise over A
        ])),
    ])
    out = _daily_weighted(conn, {"FIGI_A0000000": 0.75, "FIGI_B0000000": 0.25},
                          date(2026, 6, 1), date(2026, 6, 30))
    assert out[date(2026, 6, 2)] == pytest.approx(0.75 * 0.01 + 0.25 * 0.03)
    assert out[date(2026, 6, 3)] == pytest.approx(0.02)  # 0.75*0.02 / 0.75


# ---- spec validation at the engine boundary ----------------------------------------------


def _engine_conns():
    sym = _RoutedConn()
    bt = _RoutedConn()
    return sym, bt


def test_engine_rejects_unknown_factor_weighting_rebalance():
    sym, bt = _engine_conns()
    assert "unknown factor" in run_backtest(sym, bt, universe_conn=sym, factor="nope")["error"]
    sym, bt = _engine_conns()
    assert "unknown weighting" in run_backtest(sym, bt, universe_conn=sym, weighting="solid-gold")["error"]
    sym, bt = _engine_conns()
    assert "unknown rebalance" in run_backtest(sym, bt, universe_conn=sym, rebalance="hourly")["error"]


def test_engine_rejects_both_selections_no_silent_preference():
    sym, bt = _engine_conns()
    out = run_backtest(sym, bt, universe_conn=sym, top_pct=0.1, top_n=5)
    assert "not both" in out["error"]


def test_engine_rejects_nonpositive_top_n():
    # a negative slice would silently select all-but-N; zero selects nothing
    sym, bt = _engine_conns()
    assert "top_n must be >= 1" in run_backtest(sym, bt, universe_conn=sym, top_n=0)["error"]
    sym, bt = _engine_conns()
    assert "top_n must be >= 1" in run_backtest(sym, bt, universe_conn=sym, top_n=-5)["error"]


def test_engine_names_an_unknown_universe():
    sym = _RoutedConn([("universe_membership", _Cur(rows=[]))])
    bt = _RoutedConn()
    out = run_backtest(sym, bt, universe_conn=sym, universe_id="typo500", top_pct=0.2)
    assert "unknown or empty universe" in out["error"]
    assert "typo500" in out["error"]


def test_engine_delegates_to_the_seam_with_the_rebalance_params():
    # AC6 "delegation params reach the seam": pin that raw_factor receives the
    # point-in-time roster, the rebalance date, and the module conns
    import backtest.engine as engine_mod

    seam_calls: list = []

    def fake_raw_factor(key, members, as_of_date, *, sym_conn, alt_conn=None, macro_conn=None):
        seam_calls.append((key, sorted(members), as_of_date, alt_conn, macro_conn))
        return {}  # below the coverage gate -> the run errors out after the loop

    roster = [(f"FIGI_{i:08d}",) for i in range(50)]
    days = [(date.fromordinal(date(2026, 1, 1).toordinal() + i),) for i in range(40)]
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=roster)),
        ("min(as_of_date), max(as_of_date)", _Cur(one=(date(2025, 1, 1), date(2026, 6, 5)))),
        ("DISTINCT as_of_date", _Cur(rows=days)),
    ])
    bt = _RoutedConn()
    alt_sentinel = _RoutedConn()
    import pytest as _pytest

    monkey = _pytest.MonkeyPatch()
    monkey.setattr(engine_mod, "raw_factor", fake_raw_factor)
    try:
        out = run_backtest(sym, bt, universe_conn=sym, factor="mom_12_1", top_pct=0.2, alt_conn=alt_sentinel)
    finally:
        monkey.undo()
    assert "lacks broad coverage" in out["error"]  # empty raws -> honest refusal
    assert seam_calls, "the engine never called the seam"
    key, members, as_of, alt, macro = seam_calls[0]
    assert key == "mom_12_1"
    assert members == sorted(r[0] for r in roster)  # the point-in-time roster
    assert as_of == days[0][0]  # the rebalance date itself
    assert alt is alt_sentinel  # module conns are passed through


def test_run_persists_the_full_spec_to_sql():
    # AC6 "spec persisted to SQL": a successful run's INSERT carries the whole spec
    roster = [(f"FIGI_{i:08d}",) for i in range(50)]
    # 200 days spans Q1-Q3: at least two quarterly rebalances
    days = [(date.fromordinal(date(2026, 1, 1).toordinal() + i),) for i in range(200)]
    ret_rows = [(d, f, 0.001) for (d,) in days for (f,) in roster[:25]]

    class _BtConn(_RoutedConn):
        def __init__(self):
            super().__init__([("INSERT INTO backtest.run", _Cur(one=(77,)))])

        def transaction(self):
            from contextlib import nullcontext

            return nullcontext()

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

    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=roster)),
        ("min(as_of_date), max(as_of_date)", _Cur(one=(date(2025, 1, 1), date(2026, 6, 5)))),
        ("DISTINCT as_of_date", _Cur(rows=days)),
        # descending raws: the top-5 holding falls inside the names that have returns
        ("fact_returns a", _Cur(rows=[(f, 0.10 - i * 0.001)
                                      for i, (f,) in enumerate(roster[:30])])),
        ("SELECT as_of_date, composite_figi, pr", _Cur(rows=ret_rows)),
    ])
    bt = _BtConn()
    out = run_backtest(sym, bt, universe_conn=sym, factor="mom_12_1", top_n=5, weighting="equal",
                       rebalance="quarterly")
    assert out.get("run_id") == 77, out.get("error")
    insert = next(p for sql, p in bt.calls
                  if isinstance(p, tuple) and "INSERT INTO backtest.run" in sql)
    import json as _json

    spec = _json.loads(insert[-1])  # the last param is the spec jsonb
    assert spec == {"factor": "mom_12_1", "universe": "sp500", "top_pct": None, "top_n": 5,
                    "weighting": "equal", "rebalance": "quarterly", "cost_bps": 10.0,
                    "start_date": spec["start_date"], "end_date": spec["end_date"]}
    assert spec["start_date"] is not None  # resolved dates persist, not the request's nulls


# ---- transaction costs / turnover / significance (1A + 1B) -------------------------------


class _BtRunConn(_RoutedConn):
    """A backtest conn that yields a run_id and supports transaction()/cursor() (no DB)."""

    def __init__(self):
        super().__init__([("INSERT INTO backtest.run", _Cur(one=(77,)))])

    def transaction(self):
        from contextlib import nullcontext

        return nullcontext()

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


def _working_run(**kw):
    """A successful quarterly momentum run over a flat-return synthetic market (same top-5 held
    every rebalance, so turnover is the initial buy-in only — easy to reason about)."""
    roster = [(f"FIGI_{i:08d}",) for i in range(50)]
    days = [(date.fromordinal(date(2026, 1, 1).toordinal() + i),) for i in range(200)]
    ret_rows = [(d, f, 0.001) for (d,) in days for (f,) in roster[:25]]
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=roster)),
        ("min(as_of_date), max(as_of_date)", _Cur(one=(date(2025, 1, 1), date(2026, 6, 5)))),
        ("DISTINCT as_of_date", _Cur(rows=days)),
        ("fact_returns a", _Cur(rows=[(f, 0.10 - i * 0.001)
                                      for i, (f,) in enumerate(roster[:30])])),
        ("SELECT as_of_date, composite_figi, pr", _Cur(rows=ret_rows)),
    ])
    return run_backtest(sym, _BtRunConn(), universe_conn=sym, factor="mom_12_1", top_n=5, weighting="equal",
                        rebalance="quarterly", **kw)


def test_turnover_reported_and_costed_net_by_default():
    out = _working_run()  # default cost_bps = 10
    assert out.get("run_id") == 77, out.get("error")
    s = out["summary"]
    # initial buy-in of an equal-weight 5-name book is one-way turnover 0.5; held flat after
    assert s["turnover_total"] == pytest.approx(0.5)
    assert s["turnover_ann"] is not None and s["turnover_ann"] > 0
    # default is NET of 10 bps: cost drag present, gross block exposed alongside
    assert s["cost_bps"] == 10.0
    assert s["cost_drag_total"] == pytest.approx(0.5 * 10.0 / 1e4)
    assert s["strategy_gross"] is not None
    assert s["strategy"]["total_return"] < s["strategy_gross"]["total_return"]


def test_explicit_zero_cost_is_gross():
    s = _working_run(cost_bps=0.0)["summary"]
    assert s["cost_bps"] == 0.0
    assert s["cost_drag_total"] == 0.0
    assert s["strategy_gross"] is None  # no separate gross block when the run IS gross


def test_costs_reduce_net_return_and_expose_gross():
    gross = _working_run(cost_bps=0.0)["summary"]["strategy"]["total_return"]
    out = _working_run(cost_bps=50.0)  # 0.5% per unit one-way turnover
    s = out["summary"]
    assert s["cost_bps"] == 50.0
    # 0.5 one-way turnover × 0.5% ≈ 25 bps one-time drag
    assert s["cost_drag_total"] == pytest.approx(0.5 * 50.0 / 1e4)
    assert s["strategy_gross"]["total_return"] == pytest.approx(gross)  # gross preserved
    assert s["strategy"]["total_return"] < gross  # headline is now NET
    assert out["spec"]["cost_bps"] == 50.0


def test_spread_tstat_and_hurdle_present():
    s = _working_run()["summary"]
    assert s["spread_tstat_hurdle"] == 3.0
    assert "spread_tstat" in s
    # strategy (top-5 momentum) vs equal-weight baseline on an all-equal-return market: the
    # excess series is ~flat, so it must NOT clear the t>3 bar (no fabricated significance)
    assert s["spread_significant"] is False


def test_engine_signals_factor_without_module_conn_is_an_attributed_error():
    # fiscal_sens declares macro:UST:DEBT — running without a macro conn must name it
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=[(f"FIGI_{i:08d}",) for i in range(50)])),
        ("min(as_of_date), max(as_of_date)",
         _Cur(one=(date(2020, 1, 1), date(2026, 6, 5)))),
        ("DISTINCT as_of_date", _Cur(rows=[
            (date.fromordinal(date(2026, 1, 1).toordinal() + i),) for i in range(40)
        ])),
    ])
    bt = _RoutedConn()
    out = run_backtest(sym, bt, universe_conn=sym, factor="fiscal_sens")
    assert "requires module connection" in out["error"]
    assert "macro" in out["error"]


def test_score_weights_math_and_exclusive_start():
    # AC: the scorer's window is (start, end] — the start day itself (the last TRAINING
    # day in the optimiser's split) must be EXCLUDED from the score
    from backtest.engine import score_weights

    conn = _RoutedConn([
        ("fact_returns", _Cur(rows=[
            (date(2026, 6, 2), "FIGI_A0000000", 0.01),
            (date(2026, 6, 3), "FIGI_A0000000", 0.02),
        ])),
    ])
    out = score_weights(conn, {"FIGI_A0000000": 1.0}, date(2026, 6, 1), date(2026, 6, 3))
    assert out["n_days"] == 2
    assert out["total_return"] == pytest.approx(1.01 * 1.02 - 1)
    # the SQL bounds are exclusive-start / inclusive-end
    sql, params = conn.calls[0]
    assert "as_of_date > %s" in sql and "as_of_date <= %s" in sql
    assert params[-2:] == (date(2026, 6, 1), date(2026, 6, 3))
    # empty holding: all-None stats, never a fabricated zero
    empty = score_weights(_RoutedConn(), {}, date(2026, 6, 1), date(2026, 6, 3))
    assert empty["total_return"] is None and empty["n_days"] == 0
