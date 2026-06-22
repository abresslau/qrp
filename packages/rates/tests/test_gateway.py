"""DbRatesGateway reads. DB-free (fake conn dispatched by SQL marker)."""

from __future__ import annotations

from datetime import date, datetime

from rates.gateway import DbRatesGateway


class _Cur:
    def __init__(self, one=None, all_=None):
        self._one, self._all = one, all_ or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    def __init__(self, sets_rows=None, anchor=None, point_rows=None):
        self.sets_rows = sets_rows or []
        self.anchor = anchor
        self.point_rows = point_rows or []
        self.value_cols: list[str] = []

    def execute(self, sql, params=None):
        if "GROUP BY curve_set" in sql:
            return _Cur(all_=self.sets_rows)
        if "max(as_of_date)" in sql:
            return _Cur(one=(self.anchor,))
        if "first_published_at" in sql:  # the points query
            self.value_cols.append("first_value" if "first_value" in sql else "value")
            return _Cur(all_=self.point_rows)
        return _Cur()


def test_curve_sets_shapes_coverage_rows():
    conn = _Conn(sets_rows=[("glc", "nominal", "spot", 15, date(2026, 6, 1), date(2026, 6, 19))])
    out = DbRatesGateway(conn).curve_sets()
    assert out == [{
        "curve_set": "glc", "basis": "nominal", "rate_type": "spot", "days": 15,
        "start_date": "2026-06-01", "end_date": "2026-06-19",
    }]


def test_curve_returns_anchored_grid_latest_vintage():
    ts = datetime(2026, 6, 19, 8, 0)
    conn = _Conn(anchor=date(2026, 6, 19), point_rows=[(0.5, 3.8, ts, ts), (1.0, 4.1, ts, ts)])
    out = DbRatesGateway(conn).curve("glc", "nominal", "spot")
    assert out["as_of_date"] == "2026-06-19" and out["vintage"] == "latest"
    assert out["points"] == [{"tenor": 0.5, "value": 3.8}, {"tenor": 1.0, "value": 4.1}]
    assert conn.value_cols == ["value"]  # latest vintage reads the `value` column


def test_curve_first_vintage_reads_first_value_column():
    ts = datetime(2026, 6, 19, 8, 0)
    conn = _Conn(anchor=date(2026, 6, 19), point_rows=[(0.5, 3.7, ts, ts)])
    DbRatesGateway(conn).curve("glc", "nominal", "spot", vintage="first")
    assert conn.value_cols == ["first_value"]  # PIT read selects the immutable first value


def test_curve_empty_when_no_data_for_anchor():
    out = DbRatesGateway(_Conn(anchor=None)).curve("glc", "real", "spot")
    assert out["as_of_date"] is None and out["points"] == []
