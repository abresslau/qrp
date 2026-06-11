"""Time-weighted returns over effective-dated weight history (Story Q5.2 + Q4.5). DB-free.

The defining behavior: analytics applies the THEN-EFFECTIVE weight vector per trading
date (step function over the history), never the latest vector retroactively; the
FR-15 `returns` block compounds that series and expresses PnL only against an
operator-stated notional.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from analytics.gateway import DbAnalyticsGateway
from portfolios.gateway import read_weight_history


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _RoutedConn:
    """Routes execute() by SQL content; records calls (params must reach the SQL)."""

    def __init__(self, routes: list[tuple[str, _Cur]]):
        self._routes = routes
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        for needle, cur in self._routes:
            if needle in sql:
                return cur
        return _Cur(one=None, rows=[])


# ---- the seam --------------------------------------------------------------------------


def test_read_weight_history_groups_vectors_ascending_in_one_statement():
    conn = _RoutedConn([
        ("portfolio_weight", _Cur(rows=[
            (date(2026, 1, 1), "FIGI_A", Decimal("1.0")),
            (date(2026, 1, 3), "FIGI_A", Decimal("0.5")),
            (date(2026, 1, 3), "FIGI_B", Decimal("0.5")),
        ])),
    ])
    history = read_weight_history(conn, 7)
    assert history == [
        (date(2026, 1, 1), {"FIGI_A": Decimal("1.0")}),
        (date(2026, 1, 3), {"FIGI_A": Decimal("0.5"), "FIGI_B": Decimal("0.5")}),
    ]
    assert len(conn.calls) == 1  # one statement: no torn vectors
    assert conn.calls[0][1] == (7,)
    assert read_weight_history(_RoutedConn([]), 7) == []


# ---- effective-dated weighting ----------------------------------------------------------

_BENCH_META = (101, "Test Index", "USD")


def _gateway(history_rows, fact_rows, terms=(None, "USD"), bench_dates=()):
    port_conn = _RoutedConn([
        ("FROM portfolios.portfolio_weight", _Cur(rows=history_rows)),
        ("notional, base_currency", _Cur(one=terms)),
        ("FROM portfolios.portfolio WHERE", _Cur(one=(1,))),  # existence
    ])
    sym_conn = _RoutedConn([
        ("currency_code FROM securities", _Cur(rows=[("USD",)])),
        ("FROM fact_returns", _Cur(rows=fact_rows)),
        ("FROM instrument", _Cur(one=_BENCH_META)),
        ("FROM fact_index_returns", _Cur(rows=[(d, 0.0) for d in bench_dates])),
    ])
    return DbAnalyticsGateway(port_conn, sym_conn)


_TWO_VECTOR_HISTORY = [
    (date(2026, 1, 1), "FIGI_A", Decimal("1.0")),
    (date(2026, 1, 3), "FIGI_B", Decimal("1.0")),
]
# Closing convention (review-set): a vector dated d is in force at the CLOSE of d —
# it earns from d+1. So vector A (Jan 1) earns Jan 2 AND Jan 3 (the Jan 3 return was
# earned by what was held INTO Jan 3); vector B (Jan 3) earns from Jan 4.
_FACTS = [
    # before the first vector: must be EXCLUDED (no weights existed — never backfilled)
    (date(2025, 12, 31), "FIGI_A", 0.99),
    # the first vector's OWN date: earned by the (nonexistent) predecessor — excluded
    (date(2026, 1, 1), "FIGI_A", 0.55),
    # vector A's era: Jan 2 and Jan 3
    (date(2026, 1, 2), "FIGI_A", 0.02),
    (date(2026, 1, 3), "FIGI_A", 0.10),
    # B returns inside A's era — must NOT be used
    (date(2026, 1, 2), "FIGI_B", 0.50),
    (date(2026, 1, 3), "FIGI_B", 0.03),
    # vector B's era: from Jan 4
    (date(2026, 1, 4), "FIGI_B", 0.04),
    # A keeps returning in B's era — must NOT be used
    (date(2026, 1, 4), "FIGI_A", 0.70),
]
_DATES = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]
_EXPECTED_CUM = 1.02 * 1.10 * 1.04 - 1.0


def test_step_function_applies_the_vector_in_force_at_the_prior_close():
    gw = _gateway(_TWO_VECTOR_HISTORY, _FACTS, bench_dates=_DATES)
    out = gw.analytics(7, 101, "ALL")
    # 3 days survive: A's era (Jan 2, Jan 3 — incl. the rebalance day, earned by the
    # OUTGOING vector), then B's era (Jan 4). No look-ahead, no retroactive weights.
    r = out["returns"]
    assert r["n_days"] == 3
    assert r["cumulative_return"] == pytest.approx(_EXPECTED_CUM)
    assert r["days_below_full_coverage"] == 0
    assert r["min_coverage"] == pytest.approx(1.0)


def test_single_vector_portfolio_series_is_unchanged_regression():
    history = [
        (date(2026, 1, 1), "FIGI_A", Decimal("0.6")),
        (date(2026, 1, 1), "FIGI_B", Decimal("0.4")),
    ]
    facts = [
        (date(2026, 1, 2), "FIGI_A", 0.01),
        (date(2026, 1, 2), "FIGI_B", 0.02),
        # a partial-coverage-but-retained day: only A (0.6 of 1.0) priced -> dropped
        # (below the 0.99 floor); a 0.995-coverage day would renormalise — modelled in
        # the coverage test below
        (date(2026, 1, 3), "FIGI_A", 0.05),
        # both priced again
        (date(2026, 1, 6), "FIGI_A", 0.03),
        (date(2026, 1, 6), "FIGI_B", -0.01),
    ]
    gw = _gateway(history, facts, bench_dates=[date(2026, 1, 2), date(2026, 1, 6)])
    out = gw.analytics(7, 101, "ALL")
    d1 = 0.6 * 0.01 + 0.4 * 0.02
    d2 = 0.6 * 0.03 + 0.4 * -0.01
    # compounded over the two fully-covered days; the 60%-covered day is dropped
    assert out["returns"]["cumulative_return"] == pytest.approx((1 + d1) * (1 + d2) - 1)
    assert out["returns"]["n_days"] == 2


def test_coverage_floor_uses_the_then_effective_vectors_total():
    # two eras with DIFFERENT totals: a 0.5-priced day passes in the 0.5-total era
    # but fails in the 1.0-total era — the floor must use the era's own total
    history = [
        (date(2026, 1, 1), "FIGI_A", Decimal("0.5")),  # era 1: total 0.5
        (date(2026, 1, 5), "FIGI_A", Decimal("0.5")),  # era 2: total 1.0
        (date(2026, 1, 5), "FIGI_B", Decimal("0.5")),
    ]
    facts = [
        (date(2026, 1, 2), "FIGI_A", 0.01),  # era 1: 0.5/0.5 = full coverage -> kept
        (date(2026, 1, 6), "FIGI_A", 0.02),  # era 2: 0.5/1.0 = 50% -> dropped
    ]
    gw = _gateway(history, facts, bench_dates=[date(2026, 1, 2), date(2026, 1, 6)])
    out = gw.analytics(7, 101, "ALL")
    assert out["returns"]["n_days"] == 1
    assert out["returns"]["cumulative_return"] == pytest.approx(0.01)


def test_dead_vector_era_is_excluded_with_a_warning_not_silently():
    history = [
        (date(2026, 1, 1), "FIGI_A", Decimal("1.0")),
        (date(2026, 1, 3), "FIGI_A", Decimal("0.0")),  # liquidation/zero vector
        (date(2026, 1, 5), "FIGI_A", Decimal("1.0")),
    ]
    facts = [
        (date(2026, 1, 2), "FIGI_A", 0.01),  # era 1: kept
        (date(2026, 1, 4), "FIGI_A", 0.99),  # dead era: excluded
        (date(2026, 1, 6), "FIGI_A", 0.02),  # era 3: kept
    ]
    gw = _gateway(history, facts, bench_dates=[date(2026, 1, 2), date(2026, 1, 6)])
    out = gw.analytics(7, 101, "ALL")
    assert out["returns"]["cumulative_return"] == pytest.approx(1.01 * 1.02 - 1)
    assert "non-positive total weight" in out["warning"]
    assert "2026-01-03" in out["warning"]  # the unusable vector is NAMED


# ---- FR-15 returns block ----------------------------------------------------------------


def test_pnl_is_notional_times_cumulative_when_stated():
    gw = _gateway(
        _TWO_VECTOR_HISTORY, _FACTS, terms=(Decimal("1000000"), "USD"), bench_dates=_DATES
    )
    r = gw.analytics(7, 101, "ALL")["returns"]
    assert r["notional"] == 1000000.0
    assert r["base_currency"] == "USD"
    assert r["pnl"] == pytest.approx(1000000.0 * _EXPECTED_CUM)


def test_pnl_is_null_without_a_notional_never_fabricated():
    gw = _gateway(_TWO_VECTOR_HISTORY, _FACTS, terms=(None, "USD"), bench_dates=_DATES)
    r = gw.analytics(7, 101, "ALL")["returns"]
    assert r["notional"] is None
    assert r["pnl"] is None
    assert r["cumulative_return"] is not None  # return-space PnL still served


def test_partial_coverage_days_are_counted_honestly():
    history = [
        (date(2026, 1, 1), "FIGI_A", Decimal("0.995")),
        (date(2026, 1, 1), "FIGI_B", Decimal("0.005")),
    ]
    facts = [
        (date(2026, 1, 2), "FIGI_A", 0.01),  # 99.5% covered: kept but renormalised
        (date(2026, 1, 3), "FIGI_A", 0.02),  # same
        (date(2026, 1, 6), "FIGI_A", 0.03),  # fully covered
        (date(2026, 1, 6), "FIGI_B", 0.00),
    ]
    gw = _gateway(history, facts, bench_dates=[d for d, _, _ in facts])
    r = gw.analytics(7, 101, "ALL")["returns"]
    assert r["n_days"] == 3
    assert r["days_below_full_coverage"] == 2  # the monetised renormalisation is visible
    assert r["min_coverage"] == pytest.approx(0.995)


def test_returns_served_below_the_statistics_floor_metrics_withheld():
    # 3 obs < 20: metrics are withheld (warning), but a cumulative return is
    # meaningful and served.
    gw = _gateway(_TWO_VECTOR_HISTORY, _FACTS, bench_dates=_DATES)
    out = gw.analytics(7, 101, "ALL")
    assert out["metrics"] is None
    assert "overlapping daily observations" in out["warning"]
    assert out["returns"]["n_days"] == 3


def test_returns_window_filter_actually_excludes_out_of_window_days():
    history = [(date(2025, 6, 1), "FIGI_A", Decimal("1.0"))]
    facts = [
        (date(2025, 7, 1), "FIGI_A", 0.50),  # prior year-ish: outside YTD
        (date(2026, 1, 5), "FIGI_A", 0.01),
        (date(2026, 1, 6), "FIGI_A", 0.02),
    ]
    gw = _gateway(history, facts, bench_dates=[d for d, _, _ in facts])
    ytd = gw.analytics(7, 101, "YTD")["returns"]  # anchor 2026-01-06 -> from 2026-01-01
    assert ytd["n_days"] == 2
    assert ytd["cumulative_return"] == pytest.approx(1.01 * 1.02 - 1)  # 0.50 excluded
    full = gw.analytics(7, 101, "ALL")["returns"]
    assert full["n_days"] == 3
    assert full["cumulative_return"] == pytest.approx(1.50 * 1.01 * 1.02 - 1)


def test_returns_is_benchmark_independent():
    # the money number must not change with the benchmark picker: a benchmark that
    # misses a portfolio day still yields the SAME cumulative return (AC3 as amended)
    gw_sparse = _gateway(_TWO_VECTOR_HISTORY, _FACTS, bench_dates=[date(2026, 1, 2)])
    gw_full = _gateway(_TWO_VECTOR_HISTORY, _FACTS, bench_dates=_DATES)
    r_sparse = gw_sparse.analytics(7, 101, "ALL")["returns"]
    r_full = gw_full.analytics(7, 101, "ALL")["returns"]
    assert r_sparse["cumulative_return"] == pytest.approx(r_full["cumulative_return"])
    assert r_sparse["n_days"] == r_full["n_days"] == 3


# ---- Q4.5 as-of picker (portfolios gateway) ----------------------------------------------


def test_patch_omitted_notional_is_a_no_op_explicit_null_clears():
    # merge-patch semantics: `{}` must NOT wipe a stored notional; `notional: null` must
    from portfolios.router import PatchPortfolio, patch_portfolio

    class _GwSpy:
        def __init__(self):
            self.set_calls: list = []

        def set_notional(self, pid, notional):
            self.set_calls.append((pid, notional))
            return True

        def get(self, pid, as_of_date=None):
            return {"portfolio_id": pid}

    spy = _GwSpy()
    patch_portfolio(7, PatchPortfolio.model_validate({}), spy)
    assert spy.set_calls == []  # omitted -> untouched

    patch_portfolio(7, PatchPortfolio.model_validate({"notional": None}), spy)
    assert spy.set_calls == [(7, None)]  # explicit null -> cleared

    patch_portfolio(7, PatchPortfolio.model_validate({"notional": 5000.0}), spy)
    assert spy.set_calls[-1] == (7, 5000.0)


def test_upload_weights_replaces_the_dates_whole_vector():
    # re-uploading a date must not merge with stale rows (a ghost holding would
    # silently corrupt the TWR series): transactional DELETE-then-INSERT
    from contextlib import contextmanager

    from portfolios.gateway import DbPortfolioGateway

    class _WriteConn(_RoutedConn):
        def __init__(self):
            super().__init__([])
            self.autocommit = False
            self.txn_entered = 0

        @contextmanager
        def transaction(self):
            self.txn_entered += 1
            yield

    class _SymResolves(_RoutedConn):
        def __init__(self):
            super().__init__([("FROM securities WHERE composite_figi", _Cur(one=("FIGI_OK",)))])

    conn = _WriteConn()
    gw = DbPortfolioGateway(conn, _SymResolves())
    out = gw.upload_weights(7, date(2026, 1, 5), [("FIGI_OK", 0.5)])
    assert out["stored"] == 1
    assert conn.txn_entered == 1
    sqls = [sql for sql, _ in conn.calls]
    delete_pos = next(i for i, s in enumerate(sqls) if "DELETE FROM portfolios.portfolio_weight" in s)
    insert_pos = next(i for i, s in enumerate(sqls) if "INSERT INTO portfolios.portfolio_weight" in s)
    assert delete_pos < insert_pos  # replace, not merge


def test_upload_with_nothing_resolved_leaves_the_existing_vector_untouched():
    from contextlib import contextmanager

    from portfolios.gateway import DbPortfolioGateway

    class _WriteConn(_RoutedConn):
        def __init__(self):
            super().__init__([])
            self.autocommit = False

        @contextmanager
        def transaction(self):
            yield

    class _SymNothing(_RoutedConn):
        pass  # resolves nothing

    conn = _WriteConn()
    gw = DbPortfolioGateway(conn, _SymNothing([]))
    out = gw.upload_weights(7, date(2026, 1, 5), [("TYPO", 0.5)])
    assert out == {"stored": 0, "unresolved": ["TYPO"], "as_of_date": "2026-01-05"}
    assert not any("DELETE" in sql for sql, _ in conn.calls)  # no erase on a typo'd upload


def test_get_with_as_of_date_serves_that_vector_or_422s():
    from portfolios.gateway import DbPortfolioGateway

    class _DetailConn(_RoutedConn):
        def __init__(self):
            super().__init__([
                ("FROM portfolios.portfolio p", _Cur(
                    one=(7, "P", "C", "USD", Decimal("5000"), None)
                )),
                ("DISTINCT as_of_date", _Cur(rows=[(date(2026, 1, 3),), (date(2026, 1, 1),)])),
                ("AND as_of_date = %s", _Cur(rows=[("FIGI_A", Decimal("1.0"))])),
            ])

        @property
        def autocommit(self):
            return True

        @autocommit.setter
        def autocommit(self, v):
            pass

    gw = DbPortfolioGateway(_DetailConn(), None)
    d = gw.get(7, date(2026, 1, 1))
    assert d["shown_as_of_date"] == "2026-01-01"
    assert d["latest_as_of_date"] == "2026-01-03"
    assert d["notional"] == 5000.0
    with pytest.raises(ValueError, match="no weight vector"):
        gw.get(7, date(2025, 7, 7))
