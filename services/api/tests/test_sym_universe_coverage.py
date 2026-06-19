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


# (uid, name, members, active, px_cov, px_latest, rt_cov, rt_latest, fn_cov, fn_latest)
# Coverage denominators are the ACTIVE count: sp500 has 101 members but 100 active (1 delisted),
# and 100/100 active are priced → "ok" (the delisted name is excluded, not counted "missing").
_ROWS = [
    ("sp500", "S&P 500", 101, 100, 100, date(2026, 6, 18), 100, date(2026, 6, 18), 98, date(2026, 6, 16)),
    ("ibov", "Ibovespa", 78, 78, 60, date(2026, 6, 17), 0, None, 78, date(2026, 6, 12)),
]


def test_universe_coverage_maps_layers_and_status():
    out = DbSymGateway(_Conn(_ROWS)).universe_coverage()
    sp = next(u for u in out if u["universe_id"] == "sp500")
    assert sp["members_resolved"] == 101  # total resolved members
    assert sp["active_members"] == 100  # the delisted one is excluded from coverage
    # 100/100 active priced → ok, NOT partial — delisted name doesn't drag it down.
    assert sp["prices"] == {"covered": 100, "total": 100, "latest_date": "2026-06-18", "status": "ok"}
    assert sp["returns"]["status"] == "ok"
    assert sp["fundamentals"] == {"covered": 98, "total": 100, "latest_date": "2026-06-16", "status": "partial"}

    ib = next(u for u in out if u["universe_id"] == "ibov")
    assert ib["members_resolved"] == 78 and ib["active_members"] == 78
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


# (iso, country, tz, members, active, px_cov, px_latest, rt_cov, rt_latest, fn_cov, fn_latest)
_BY_COUNTRY = [
    ("US", "United States", "America/New_York", 1791, 1790, 1778, date(2026, 6, 18),
     1778, date(2026, 6, 18), 1761, date(2026, 6, 16)),
    ("BR", "Brazil", "America/Sao_Paulo", 99, 99, 99, date(2026, 6, 18),
     99, date(2026, 6, 18), 79, date(2026, 6, 12)),
]


def test_coverage_by_country_active_only_and_shape():
    out = DbSymGateway(_Conn(_BY_COUNTRY)).coverage_by_country()
    us = next(c for c in out if c["country_iso"] == "US")
    assert us["country"] == "United States" and us["timezone"] == "America/New_York"
    assert us["members"] == 1791 and us["active_members"] == 1790  # 1 delisted excluded
    # coverage denominator is the active count (1790), not all members (1791)
    assert us["prices"] == {"covered": 1778, "total": 1790, "latest_date": "2026-06-18", "status": "partial"}
    br = next(c for c in out if c["country_iso"] == "BR")
    assert br["prices"]["status"] == "ok" and br["fundamentals"]["status"] == "partial"


def test_coverage_by_country_universe_filter_is_parameterized_and_bounded():
    conn = _Conn(_BY_COUNTRY)
    DbSymGateway(conn).coverage_by_country("sp500")
    sql = next(s for s in conn.seen if "WITH members" in s).lower()
    assert "universe_id = %(uni)s" in sql  # universe filter is parameterized (not interpolated)
    assert "group by ex.country_iso" in sql  # grouped by country
    assert "join exchange ex" in sql  # country/timezone come from exchange
    assert "count(distinct" not in sql  # never the full-table distinct trap
