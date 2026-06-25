"""Security price history (detail-page chart) — DB-free fake conn + index-bound guard."""

from __future__ import annotations

from datetime import date

from qrp_api.modules.sym.gateway import DbSymGateway


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows
        self.seen: list[str] = []
        self.params: list = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        self.params.append(params)
        return _Cur(self._rows)


# (session_date, open, high, low, close, volume)
_ROWS = [
    (date(2026, 6, 16), 100.0, 105.0, 99.0, 104.0, 1_000_000),
    (date(2026, 6, 17), 104.0, 106.0, 101.0, 102.0, 1_200_000),
    (date(2026, 6, 18), 102.0, 103.0, None, None, None),  # a partial bar degrades to nulls
]


def test_security_prices_maps_ohlcv_oldest_first():
    out = DbSymGateway(_Conn(_ROWS), equity_conn=_Conn(_ROWS)).security_prices("F1", days=90)
    assert [b["session_date"] for b in out] == ["2026-06-16", "2026-06-17", "2026-06-18"]
    assert out[0] == {
        "session_date": "2026-06-16",
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 104.0,
        "volume": 1_000_000,
    }
    # nulls survive as None (a partial bar never crashes the chart)
    assert out[2]["low"] is None and out[2]["close"] is None and out[2]["volume"] is None


def test_security_prices_is_index_bounded():
    conn = _Conn(_ROWS)
    DbSymGateway(conn, equity_conn=conn).security_prices("F1", days=30)
    sql = conn.seen[0].lower()
    assert "from prices_raw" in sql
    assert "composite_figi = %s" in sql  # rides the PK, per-figi
    assert "session_date >=" in sql  # bounded recent window, not a full scan
    assert conn.params[0] == ("F1", "F1", 30)  # (figi, figi, days)
