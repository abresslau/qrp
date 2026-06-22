"""Derived-spread gateway (history + z-score). DB-free (fake conn keyed by leg-group params)."""

from __future__ import annotations

from datetime import date

import pytest

from rates.gateway import DbRatesGateway


class _Cur:
    def __init__(self, all_=None):
        self._all = all_ or []

    def fetchall(self):
        return self._all

    def fetchone(self):
        return self._all[0] if self._all else None


class _Conn:
    """rows_by_group: {(curve_set, basis, rate_type): [(date, tenor, value), ...]}.
    Filters to the requested tenors (the gateway passes tenor = ANY(list))."""

    def __init__(self, rows_by_group):
        self.rows_by_group = rows_by_group

    def execute(self, sql, params=None):
        if "as_of_date, tenor, value FROM rates.curve_point" in sql:
            cs, b, rt, tenors = params
            rows = self.rows_by_group.get((cs, b, rt), [])
            want = set(tenors)
            return _Cur([(d, t, v) for d, t, v in rows if t in want])
        return _Cur()


D1, D2 = date(2026, 6, 1), date(2026, 6, 2)


def test_2s10s_series_value_and_zscore():
    # day1: 10y-2y = 4.5-4.0 = 50bp ; day2: 4.6-4.0 = 60bp ; current=60, mean=55, pstdev=5 -> z=1.0
    conn = _Conn({("glc", "nominal", "spot"): [
        (D1, 2.0, 4.0), (D1, 10.0, 4.5), (D2, 2.0, 4.0), (D2, 10.0, 4.6),
    ]})
    s = next(x for x in DbRatesGateway(conn).spreads() if x["key"] == "2s10s")
    assert s["unit"] == "bp" and s["as_of_date"] == "2026-06-02"
    assert s["value"] == pytest.approx(60.0)
    assert s["zscore"] == pytest.approx(1.0) and s["percentile"] == pytest.approx(100.0)
    assert [p["value"] for p in s["history"]] == [pytest.approx(50.0), pytest.approx(60.0)]


def test_breakeven_is_na_when_real_leg_missing():
    # nominal present, real absent -> the be10y spread has no complete date -> N/A nulls
    conn = _Conn({("glc", "nominal", "spot"): [(D1, 10.0, 4.5)]})
    be = next(x for x in DbRatesGateway(conn).spreads() if x["key"] == "be10y")
    assert be["value"] is None and be["zscore"] is None and be["history"] == []


def test_breakeven_level_in_percent():
    conn = _Conn({
        ("glc", "nominal", "spot"): [(D1, 10.0, 4.5)],
        ("glc", "real", "spot"): [(D1, 10.0, 1.0)],
    })
    be = next(x for x in DbRatesGateway(conn).spreads() if x["key"] == "be10y")
    assert be["unit"] == "%" and be["value"] == pytest.approx(3.5)


def test_spread_history_window_filter_and_unknown_key():
    conn = _Conn({("glc", "nominal", "spot"): [
        (date(2020, 1, 1), 2.0, 3.0), (date(2020, 1, 1), 10.0, 3.5),  # old (outside 1Y)
        (D2, 2.0, 4.0), (D2, 10.0, 4.6),
    ]})
    gw = DbRatesGateway(conn)
    assert len(gw.spread_history("2s10s", "MAX")["points"]) == 2
    assert len(gw.spread_history("2s10s", "1Y")["points"]) == 1  # only the recent date survives
    assert gw.spread_history("does-not-exist")["points"] == []
