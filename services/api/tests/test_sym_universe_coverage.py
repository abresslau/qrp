"""Per-universe Prices/Returns/Fundamentals coverage — DB-free fake conn + perf guard."""

from __future__ import annotations

from datetime import date

from qrp_api.modules.sym.gateway import DbSymGateway


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "max(session_date) FROM prices_raw" in sql:
            return _Cur(one=(date(2026, 6, 18),))
        if "min(window_id) FROM return_window" in sql:
            return _Cur(one=(1,))
        if "WITH members" in sql:
            return _Cur(rows=self._rows)
        return _Cur()


# (uid, name, total, px_cov, px_latest, rt_cov, rt_latest, fn_cov, fn_latest)
_ROWS = [
    ("sp500", "S&P 500", 100, 100, date(2026, 6, 18), 100, date(2026, 6, 18), 98, date(2026, 6, 16)),
    ("ibov", "Ibovespa", 78, 60, date(2026, 6, 17), 0, None, 78, date(2026, 6, 12)),
]


def test_universe_coverage_maps_layers_and_status():
    out = DbSymGateway(_Conn(_ROWS)).universe_coverage()
    sp = next(u for u in out if u["universe_id"] == "sp500")
    assert sp["members_resolved"] == 100
    assert sp["prices"] == {"covered": 100, "total": 100, "latest_date": "2026-06-18", "status": "ok"}
    assert sp["returns"]["status"] == "ok"
    assert sp["fundamentals"] == {"covered": 98, "total": 100, "latest_date": "2026-06-16", "status": "partial"}

    ib = next(u for u in out if u["universe_id"] == "ibov")
    assert ib["prices"]["status"] == "partial"  # 60/78
    assert ib["returns"] == {"covered": 0, "total": 78, "latest_date": None, "status": "missing"}
    assert ib["fundamentals"]["status"] == "ok"  # 78/78 (low-cadence: any recent counts)


def test_universe_coverage_query_is_index_bounded_not_full_table():
    # perf guard (the Overview 125s lesson): the coverage scan must restrict returns to one
    # window_id and bound by a recent date — NEVER a full-table count(DISTINCT)/group-by-date.
    conn = _Conn(_ROWS)
    DbSymGateway(conn).universe_coverage()
    cov_sql = next(s for s in conn.seen if "WITH members" in s).lower()
    assert "window_id = %(w)s" in cov_sql  # returns restricted to one window (not 28×)
    assert "session_date >= %(latest)s" in cov_sql  # bounded recent window
    assert "count(distinct" not in cov_sql  # never the full-table distinct trap
    assert "group by session_date" not in cov_sql


def test_universe_coverage_empty_when_no_prices():
    out = DbSymGateway(_Conn([])).universe_coverage()
    # max(session_date) returns a date in the fake, so it proceeds; with no member rows → []
    assert out == []
