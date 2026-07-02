"""Strategy-spec engine tests (Story Q6.3 + Q9.4) — fake conns, no network/DB."""

from __future__ import annotations

from datetime import date

import pytest

from backtest.engine import (
    _aligned_returns_asof,
    _cap_weights,
    _daily_weighted,
    _min_variance_weights,
    _neutral_weights,
    _rebalance_dates,
    _select_long_short,
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


# ---- long/short selection (Sharpe-ranked, sticky) ----------------------------------------


def test_select_long_short_longs_top_shorts_bottom_disjoint():
    longs, shorts = _select_long_short(_RAW, "high", None, 2, None, 2, set(), set(), 1.5)
    assert longs == ["A", "B"]          # best by value
    assert shorts == ["E", "D"]         # worst by value (worst-first)
    assert not (set(longs) & set(shorts))  # a name is never both a long and a short


def test_select_long_short_long_leg_matches_select_top():
    # the long leg selection is the same ranking _select_top uses (consistency with long-only)
    longs, _ = _select_long_short(_RAW, "high", 0.4, None, None, 1, set(), set(), 1.5)
    assert longs == _select_top(_RAW, "high", 0.4, None)


def test_sticky_selection_reduces_turnover_vs_hard_cutoff():
    # C was held last rebalance; it has drifted to rank 4 (just outside the top-3 entry cut) but
    # is still inside the keep band (top ceil(3*1.5)=5). A hard cutoff drops it for D (a swap);
    # sticky RETAINS it -> zero name churn on the long leg. This is AC-4's turnover damping.
    raw_t2 = {"A": 5.0, "B": 4.0, "D": 3.0, "C": 2.5, "E": 1.0}
    prev_held = {"A", "B", "C"}
    hard, _ = _select_long_short(raw_t2, "high", None, 3, None, 1, set(), set(), 1.5)
    sticky, _ = _select_long_short(raw_t2, "high", None, 3, None, 1, prev_held, set(), 1.5)
    assert hard == ["A", "B", "D"]        # C fell out; D took its slot
    assert set(sticky) == {"A", "B", "C"}  # C retained within the keep band
    hard_churn = len(set(hard) ^ prev_held)
    sticky_churn = len(set(sticky) ^ prev_held)
    assert sticky_churn < hard_churn      # sticky selection churns fewer names


# ---- signed dollar-neutral weighting ------------------------------------------------------


def test_neutral_weights_inverse_vol_net_zero_gross_one_and_drops_no_vol():
    # longs A,B ; shorts C,D — but D has no positive vol_tr row -> dropped from the short leg
    eq = _RoutedConn([("fact_asset_metrics", _Cur(rows=[
        ("A", 0.10), ("B", 0.20), ("C", 0.40),  # D absent
    ]))])
    w, dl, ds = _neutral_weights(eq, ["A", "B"], ["C", "D"], date(2026, 6, 1),
                                 "inverse_vol", 0.5, 0.5)
    assert ds == 1 and dl == 0                      # D dropped, counted (never zero-weighted)
    assert "D" not in w
    assert w["A"] > 0 and w["B"] > 0 and w["C"] < 0  # signs from the leg
    assert sum(w.values()) == pytest.approx(0.0)     # dollar-neutral (net 0)
    assert sum(abs(v) for v in w.values()) == pytest.approx(1.0)  # gross 1
    # inverse-vol: the lower-vol long (A, vol 0.10) carries more weight than B (vol 0.20)
    assert w["A"] > w["B"]
    # the read pins window 11 + gated=false + positive vol + the >=60-obs floor (no thin-name blowup)
    sql, params = eq.calls[0]
    assert "window_id=%s" in sql and "gated=false" in sql and "vol_tr > 0" in sql
    assert "n_obs >= %s" in sql and 60 in params


def test_neutral_weights_equal_splits_each_side_no_vol_read():
    eq = _RoutedConn()  # equal weighting needs no fact_asset_metrics read
    w, dl, ds = _neutral_weights(eq, ["A", "B"], ["C", "D"], date(2026, 6, 1), "equal", 0.5, 0.5)
    assert w == {"A": 0.25, "B": 0.25, "C": -0.25, "D": -0.25}
    assert sum(w.values()) == pytest.approx(0.0)
    assert sum(abs(v) for v in w.values()) == pytest.approx(1.0)
    assert dl == 0 and ds == 0
    assert not eq.calls  # no DB read for equal


# ---- the net-zero _daily_weighted fix (THE load-bearing correctness fix) ------------------


def test_daily_weighted_signed_book_is_non_empty_and_rescaled_by_gross():
    # a dollar-neutral book (Σw = 0). The OLD ÷Σw / `if cw>0` gate dropped EVERY day (empty
    # backtest); dividing by GROSS present keeps the series and computes Σ(w·pr)/Σ|w|.
    conn = _RoutedConn([("fact_returns", _Cur(rows=[
        (date(2026, 6, 2), "FIGI_LONG00000", 0.02),
        (date(2026, 6, 2), "FIGI_SHORT0000", 0.01),
        (date(2026, 6, 3), "FIGI_LONG00000", 0.03),  # short unpriced: rescale by gross present
    ]))])
    w = {"FIGI_LONG00000": 0.5, "FIGI_SHORT0000": -0.5}
    out = _daily_weighted(conn, w, date(2026, 6, 1), date(2026, 6, 30))
    assert out, "dollar-neutral book must produce a non-empty daily series (net-zero trap)"
    # day 1: (0.5*0.02 + -0.5*0.01) / (0.5+0.5) = 0.005
    assert out[date(2026, 6, 2)] == pytest.approx(0.005)
    # day 2: only the long priced -> 0.5*0.03 / 0.5 = 0.03 (rescaled by gross present, not net)
    assert out[date(2026, 6, 3)] == pytest.approx(0.03)


def test_daily_weighted_long_only_unchanged_by_the_fix():
    # regression: an all-positive book is byte-identical to the historical Σ(w·pr)/Σw
    conn = _RoutedConn([("fact_returns", _Cur(rows=[
        (date(2026, 6, 2), "FIGI_A0000000", 0.01),
        (date(2026, 6, 2), "FIGI_B0000000", 0.03),
        (date(2026, 6, 3), "FIGI_A0000000", 0.02),  # B unpriced: renormalise over A
    ]))])
    out = _daily_weighted(conn, {"FIGI_A0000000": 0.75, "FIGI_B0000000": 0.25},
                          date(2026, 6, 1), date(2026, 6, 30))
    assert out[date(2026, 6, 2)] == pytest.approx(0.75 * 0.01 + 0.25 * 0.03)
    assert out[date(2026, 6, 3)] == pytest.approx(0.02)  # 0.75*0.02 / 0.75


# ---- min_variance weighting (covariance-aware, as-of-bounded) -----------------------------


def test_aligned_returns_asof_is_upper_bounded_by_the_rebalance_date():
    # the #1 look-ahead guardrail: the covariance read must be capped at the rebalance date d
    conn = _RoutedConn([("SELECT as_of_date, composite_figi, pr", _Cur(rows=[]))])
    d = date(2025, 6, 30)
    _aligned_returns_asof(conn, ["FIGI_A0000000", "FIGI_B0000000"], d, lookback=252)
    sql, params = conn.calls[0]
    assert "as_of_date <= %s" in sql and "as_of_date > %s - %s::int" in sql
    # d appears as BOTH the inclusive upper bound and the lookback anchor (never a global max)
    assert params == (1, ["FIGI_A0000000", "FIGI_B0000000"], d, d, 252)
    assert "max(as_of_date)" not in sql  # NOT the optimiser's global-max bounding


def test_min_variance_weights_are_dollar_neutral_via_the_optimiser():
    # 2 longs + 2 shorts, 40 aligned days with a shared market factor (genuine covariance). The
    # optimiser solve must return a signed net≈0 / gross≈1 book (real optimiser math, no mocks).
    longs, shorts = ["FIGI_L0000000", "FIGI_L1000000"], ["FIGI_S0000000", "FIGI_S1000000"]
    figis = longs + shorts
    d0 = date(2025, 1, 1)
    rows = []
    for k in range(40):
        dd = date.fromordinal(d0.toordinal() + k)
        mkt = 0.01 * ((-1) ** k)
        for i, f in enumerate(figis):
            rows.append((dd, f, (0.5 + 0.2 * i) * mkt + 0.001 * ((-1) ** (k + i))))
    conn = _RoutedConn([("SELECT as_of_date, composite_figi, pr", _Cur(rows=rows))])
    w, dropped = _min_variance_weights(
        conn, longs, shorts, date(2025, 3, 1), long_mass=0.5, short_mass=0.5,
        lookback=252, cov_method="shrinkage", leg_cap=60,
    )
    assert dropped == 0
    assert sum(w.values()) == pytest.approx(0.0, abs=1e-6)          # dollar-neutral
    assert sum(abs(v) for v in w.values()) == pytest.approx(1.0, abs=1e-6)  # gross 1
    assert all(w[f] > 0 for f in longs) and all(w[f] < 0 for f in shorts)


def test_min_variance_weights_skips_when_history_too_short():
    # < 30 aligned days → no covariance → empty book (caller skips the rebalance), names counted
    conn = _RoutedConn([("SELECT as_of_date, composite_figi, pr", _Cur(rows=[
        (date(2025, 1, 1), "FIGI_L0000000", 0.01), (date(2025, 1, 1), "FIGI_S0000000", 0.02),
    ]))])
    w, dropped = _min_variance_weights(
        conn, ["FIGI_L0000000"], ["FIGI_S0000000"], date(2025, 3, 1),
        long_mass=0.5, short_mass=0.5, lookback=252, cov_method="shrinkage", leg_cap=60,
    )
    assert w == {} and dropped == 2


def test_engine_rejects_min_variance_without_shorts():
    sym, bt = _engine_conns()
    out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, weighting="min_variance")
    assert "min_variance weighting requires a short selector" in out["error"]


def test_engine_rejects_borrow_bps_without_shorts():
    # borrow_bps finances the short leg — a long-only run must reject it, not silently ignore it
    sym, bt = _engine_conns()
    out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, borrow_bps=50.0)
    assert "borrow_bps finances the short leg" in out["error"]


def test_min_variance_weights_counts_leg_cap_trims_as_dropped():
    # leg_cap=1 trims the 2-name legs to 1 each; the 2 trimmed names must be counted in `dropped`
    longs, shorts = ["FIGI_L0000000", "FIGI_L1000000"], ["FIGI_S0000000", "FIGI_S1000000"]
    figis = longs + shorts
    d0 = date(2025, 1, 1)
    rows = []
    for k in range(40):
        dd = date.fromordinal(d0.toordinal() + k)
        mkt = 0.01 * ((-1) ** k)
        for i, f in enumerate(figis):
            rows.append((dd, f, (0.5 + 0.2 * i) * mkt + 0.001 * ((-1) ** (k + i))))
    conn = _RoutedConn([("SELECT as_of_date, composite_figi, pr", _Cur(rows=rows))])
    w, dropped = _min_variance_weights(
        conn, longs, shorts, date(2025, 3, 1), long_mass=0.5, short_mass=0.5,
        lookback=252, cov_method="shrinkage", leg_cap=1,
    )
    assert len(w) == 2 and dropped == 2  # 4 selected − 2 held = 2 trimmed by the leg cap, counted
    assert sum(w.values()) == pytest.approx(0.0, abs=1e-6)


def test_aligned_returns_asof_keeps_the_two_name_set_after_trimming():
    # A,B priced 40 days; C priced only 10 -> the full 3-set has <30 common dates, so C is trimmed
    # and the 2-name {A,B} set (which DOES have >=30) must be RETURNED, not rejected.
    d0 = date(2025, 1, 1)
    rows = []
    for k in range(40):
        dd = date.fromordinal(d0.toordinal() + k)
        rows.append((dd, "FIGI_A0000000", 0.001 * ((-1) ** k)))
        rows.append((dd, "FIGI_B0000000", 0.002 * ((-1) ** k)))
        if k < 10:  # C is sparse
            rows.append((dd, "FIGI_C0000000", 0.003))
    conn = _RoutedConn([("SELECT as_of_date, composite_figi, pr", _Cur(rows=rows))])
    figis, matrix = _aligned_returns_asof(
        conn, ["FIGI_A0000000", "FIGI_B0000000", "FIGI_C0000000"], date(2025, 3, 1), lookback=252)
    assert set(figis) == {"FIGI_A0000000", "FIGI_B0000000"}  # C trimmed, 2-name set kept
    assert len(matrix[0]) >= 30


def test_borrow_cost_accrues_on_the_short_leg_separate_from_turnover():
    # a dollar-neutral book with borrow but NO turnover cost: the drag is all borrow, the headline
    # is NET (costed), and borrow_cost_total is reported separately and > 0.
    out = _long_short_run(cost_bps=0.0, borrow_bps=100.0)
    assert out.get("run_id") == 77, out.get("error")
    s = out["summary"]
    assert s["borrow_bps"] == 100.0
    assert s["borrow_cost_total"] > 0.0
    # short gross ~0.5 financed daily; drag = 0.5 * (100/1e4)/252 per common day
    assert s["borrow_cost_total"] == pytest.approx(out["n_days"] * 0.5 * (100 / 1e4) / 252, rel=1e-6)
    assert s["cost_drag_total"] == pytest.approx(s["borrow_cost_total"])  # cost_bps=0 → no turnover
    assert s["strategy_gross"] is not None  # borrow makes the run costed → net headline + gross block


def test_long_short_run_has_zero_borrow_by_default():
    s = _long_short_run(cost_bps=0.0)["summary"]  # no borrow_bps
    assert s["borrow_cost_total"] == 0.0
    assert s["borrow_bps"] == 0.0


# ---- cap weighting -----------------------------------------------------------------------


def test_cap_weights_proportional_and_drops_capless_names_counted():
    # the seam's size factor returns mcaps; one name has none ON/before d -> dropped + counted
    conn = _RoutedConn([
        ("fundamentals", _Cur(rows=[("FIGI_BIG00000", 300e9), ("FIGI_SML00000", 100e9)])),
    ])
    weights, dropped = _cap_weights(conn, conn, ["FIGI_BIG00000", "FIGI_SML00000", "FIGI_NOCAP00"],
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
    assert "unknown factor" in run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, factor="nope")["error"]
    sym, bt = _engine_conns()
    assert "unknown weighting" in run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, weighting="solid-gold")["error"]
    sym, bt = _engine_conns()
    assert "unknown rebalance" in run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, rebalance="hourly")["error"]


def test_engine_rejects_both_selections_no_silent_preference():
    sym, bt = _engine_conns()
    out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, top_pct=0.1, top_n=5)
    assert "not both" in out["error"]


def test_engine_rejects_both_long_or_short_selectors_and_cap_with_shorts():
    sym, bt = _engine_conns()
    assert "long_pct OR long_n" in run_backtest(
        sym, bt, universe_conn=sym, equity_conn=sym, long_pct=0.1, long_n=5, short_n=5)["error"]
    sym, bt = _engine_conns()
    assert "short_pct OR short_n" in run_backtest(
        sym, bt, universe_conn=sym, equity_conn=sym, short_pct=0.1, short_n=5)["error"]
    sym, bt = _engine_conns()
    # cap weighting has no meaning on a short leg — reject the combo loudly
    assert "cap weighting is long-only" in run_backtest(
        sym, bt, universe_conn=sym, equity_conn=sym, weighting="cap", short_n=5)["error"]


def test_engine_rejects_cross_mode_selectors_not_silently_ignored():
    # long_* without a short selector, or top_* with shorts, would be silently dropped — reject.
    sym, bt = _engine_conns()
    assert "require a short selector" in run_backtest(
        sym, bt, universe_conn=sym, equity_conn=sym, long_n=5)["error"]
    sym, bt = _engine_conns()
    assert "long-only" in run_backtest(
        sym, bt, universe_conn=sym, equity_conn=sym, top_pct=0.1, short_n=5)["error"]


def test_engine_rejects_nonpositive_top_n():
    # a negative slice would silently select all-but-N; zero selects nothing
    sym, bt = _engine_conns()
    assert "top_n must be >= 1" in run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, top_n=0)["error"]
    sym, bt = _engine_conns()
    assert "top_n must be >= 1" in run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, top_n=-5)["error"]


def test_engine_names_an_unknown_universe():
    sym = _RoutedConn([("universe_membership", _Cur(rows=[]))])
    bt = _RoutedConn()
    out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, universe_id="typo500", top_pct=0.2)
    assert "unknown or empty universe" in out["error"]
    assert "typo500" in out["error"]


def test_engine_delegates_to_the_seam_with_the_rebalance_params():
    # AC6 "delegation params reach the seam": pin that raw_factor receives the
    # point-in-time roster, the rebalance date, and the module conns
    import backtest.engine as engine_mod

    seam_calls: list = []

    def fake_raw_factor(key, members, as_of_date, *, sym_conn, eq_conn=None, alt_conn=None, macro_conn=None):
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
        out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, factor="mom_12_1", top_pct=0.2, alt_conn=alt_sentinel)
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
    out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, factor="mom_12_1", top_n=5, weighting="equal",
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
    return run_backtest(sym, _BtRunConn(), universe_conn=sym, equity_conn=sym, factor="mom_12_1", top_n=5, weighting="equal",
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
    out = run_backtest(sym, bt, universe_conn=sym, equity_conn=sym, factor="fiscal_sens")
    assert "requires module connection" in out["error"]
    assert "macro" in out["error"]


def _long_short_run(**kw):
    """A dollar-neutral long/short momentum run on a FLAT synthetic market (all daily pr=0.001).

    30 names carry momentum raws (descending) so the long leg = the 5 best, the short leg = the 5
    worst; all 30 price every day, so both legs are fully covered. A dollar-neutral book on a flat
    market has ~zero gross return — the market-neutrality this story targets.
    """
    roster = [(f"FIGI_{i:08d}",) for i in range(50)]
    days = [(date.fromordinal(date(2026, 1, 1).toordinal() + i),) for i in range(200)]
    ret_rows = [(d, f, 0.001) for (d,) in days for (f,) in roster[:30]]
    sym = _RoutedConn([
        ("universe_membership", _Cur(rows=roster)),
        ("min(as_of_date), max(as_of_date)", _Cur(one=(date(2025, 1, 1), date(2026, 6, 5)))),
        ("DISTINCT as_of_date", _Cur(rows=days)),
        ("fact_returns a", _Cur(rows=[(f, 0.10 - i * 0.001)
                                      for i, (f,) in enumerate(roster[:30])])),
        ("SELECT as_of_date, composite_figi, pr", _Cur(rows=ret_rows)),
    ])
    return run_backtest(
        sym, _BtRunConn(), universe_conn=sym, equity_conn=sym, factor="mom_12_1",
        long_n=5, short_n=5, weighting="equal", rebalance="quarterly", **kw,
    )


def test_long_short_run_is_dollar_neutral_and_non_empty():
    out = _long_short_run()
    assert out.get("run_id") == 77, out.get("error")
    s = out["summary"]
    # AC-6 book diagnostics: net ≈ 0, gross ≈ 1, and both legs sized 5
    assert s["net_exposure"] == pytest.approx(0.0, abs=1e-9)
    assert s["gross_exposure"] == pytest.approx(1.0)
    assert s["n_long"] == 5 and s["n_short"] == 5
    # the net-zero fix: the dollar-neutral book produced a non-empty daily series
    assert out["n_days"] > 0
    # a dollar-neutral book on a flat market earns ~0 gross (market-neutral)
    assert s["strategy_gross"]["total_return"] == pytest.approx(0.0, abs=1e-9)
    # the long/short spec fields persist for reproducibility
    assert out["spec"]["long_n"] == 5 and out["spec"]["short_n"] == 5
    assert out["spec"]["sticky_keep_mult"] == 1.5


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
