"""DbCommoditiesGateway.board period-return math — DB-free (fake conn by SQL marker)."""

from __future__ import annotations

from datetime import date, timedelta

from commodity.gateway import DbCommoditiesGateway


class _Cur:
    def __init__(self, one=None, all_=None):
        self._one, self._all = one, all_ or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    def __init__(self, maxd, rows):
        self.maxd = maxd
        self.rows = rows

    def execute(self, sql, params=None):
        if "ORDER BY commodity_code, as_of_date" in sql:  # the board window query
            return _Cur(all_=self.rows)
        if "max(as_of_date)" in sql:  # board's anchor
            return _Cur(one=(self.maxd,))
        return _Cur()


def _series(code, start, n, base, step):
    return [(code, start + timedelta(days=i), base + i * step, 1000.0) for i in range(n)]


def test_board_computes_daily_change_and_shape():
    start = date(2025, 5, 1)
    n = 420
    rows = _series("WTI", start, n, 50.0, 0.1)  # rising series
    maxd = start + timedelta(days=n - 1)
    out = DbCommoditiesGateway(_Conn(maxd, rows)).board()
    assert len(out) == 1
    r = out[0]
    assert r["code"] == "WTI" and r["name"] == "WTI Crude Oil" and r["sector"] == "energy"
    last = 50.0 + (n - 1) * 0.1
    prev = 50.0 + (n - 2) * 0.1
    assert abs(r["last"] - last) < 1e-9
    assert abs(r["chg_1d"] - (last - prev)) < 1e-9
    assert abs(r["pct_1d"] - (last / prev - 1) * 100) < 1e-9
    # period anchors exist within the 420-day window → all returns are finite & positive (rising)
    for k in ("pct_1w", "pct_1m", "pct_ytd", "pct_1y"):
        assert r[k] is not None and r[k] > 0
    assert len(r["spark"]) == 120  # default spark_n


def test_board_empty_when_no_data():
    assert DbCommoditiesGateway(_Conn(None, [])).board() == []


def test_board_sorts_by_sector_then_name():
    start = date(2025, 5, 1)
    rows = _series("GOLD", start, 5, 2000.0, 1.0) + _series("WTI", start, 5, 50.0, 0.1)
    maxd = start + timedelta(days=4)
    out = DbCommoditiesGateway(_Conn(maxd, rows)).board()
    # energy (WTI) sorts before precious_metals (GOLD)
    assert [r["code"] for r in out] == ["WTI", "GOLD"]
