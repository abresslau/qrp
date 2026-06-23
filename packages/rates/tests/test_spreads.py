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


class _MovieConn:
    def __init__(self, dates, points_by_date):
        self.dates = dates
        self.pbd = points_by_date

    def execute(self, sql, params=None):
        if "DISTINCT as_of_date" in sql:
            return _Cur(all_=[(d,) for d in self.dates])
        if "as_of_date, tenor, value" in sql:
            sampled = set(params[3])
            rows = []
            for d in self.dates:
                if d in sampled:
                    for t, v in self.pbd[d]:
                        rows.append((d, t, v))
            return _Cur(all_=rows)
        return _Cur()


def test_curve_movie_samples_evenly_with_first_and_last():
    dates = [date(2000, 1, 1 + i) for i in range(10)]
    pbd = {d: [(2.0, 4.0 + i * 0.1), (10.0, 4.5 + i * 0.1)] for i, d in enumerate(dates)}
    m = DbRatesGateway(_MovieConn(dates, pbd)).curve_movie("glc", "nominal", "spot", frames=4)
    fr = m["frames"]
    assert 2 <= len(fr) <= 4
    assert fr[0]["as_of_date"] == dates[0].isoformat()  # oldest always first
    assert fr[-1]["as_of_date"] == dates[-1].isoformat()  # latest always last
    assert fr[0]["points"][0] == {"tenor": 2.0, "value": 4.0}


def test_curve_movie_empty_series():
    assert DbRatesGateway(_MovieConn([], {})).curve_movie("ois", "real", "spot")["frames"] == []


def test_curve_movie_start_date_windows_the_history():
    dates = [date(2000, 1, 1 + i) for i in range(10)]
    pbd = {d: [(2.0, 4.0)] for d in dates}
    m = DbRatesGateway(_MovieConn(dates, pbd)).curve_movie(
        "glc", "nominal", "spot", frames=10, start_date=date(2000, 1, 6)
    )
    fr = m["frames"]
    assert fr[0]["as_of_date"] == "2000-01-06"  # window starts at start_date
    assert fr[-1]["as_of_date"] == "2000-01-10"


def test_spread_history_window_filter_and_unknown_key():
    conn = _Conn({("glc", "nominal", "spot"): [
        (date(2020, 1, 1), 2.0, 3.0), (date(2020, 1, 1), 10.0, 3.5),  # old (outside 1Y)
        (D2, 2.0, 4.0), (D2, 10.0, 4.6),
    ]})
    gw = DbRatesGateway(conn)
    assert len(gw.spread_history("2s10s", "MAX")["points"]) == 2
    assert len(gw.spread_history("2s10s", "1Y")["points"]) == 1  # only the recent date survives
    assert gw.spread_history("does-not-exist")["points"] == []
