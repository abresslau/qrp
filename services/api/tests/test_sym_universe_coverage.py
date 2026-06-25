"""Per-universe Prices/Returns/Fundamentals coverage — DB-free fake conns + perf guard.

Cross-DB now: the resolved-member roster comes from the universe DB; the per-figi sym facts
(status + prices/returns/fundamentals recency) from sym, aggregated per universe in Python."""

from __future__ import annotations

from datetime import date

from qrp_api.modules.sym.gateway import DbSymGateway

LATEST = date(2026, 6, 18)
RECENT = date(2026, 6, 11)  # LATEST - 7


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


# Synthetic members so the Python aggregation reproduces the documented per-layer outcomes.
# sp500: 101 resolved (100 active + 1 delisted); 100/100 active priced + with returns; 98 with
#        fundamentals. ibov: 78 active; 60 priced, 0 returns, 78 fundamentals.
def _roster() -> list[tuple]:
    rows = [("sp500", "S&P 500", f"SP{i:010d}") for i in range(101)]
    rows += [("ibov", "Ibovespa", f"IB{i:010d}") for i in range(78)]
    return rows


def _facts() -> dict[str, tuple]:
    facts: dict[str, tuple] = {}
    for i in range(101):  # sp500
        figi = f"SP{i:010d}"
        if i == 100:
            facts[figi] = ("delisted", None, None, None)  # excluded from coverage denominators
        else:
            fn = date(2026, 6, 16) if i < 98 else None
            facts[figi] = ("active", LATEST, LATEST, fn)
    for i in range(78):  # ibov
        figi = f"IB{i:010d}"
        px = date(2026, 6, 17) if i < 60 else None
        facts[figi] = ("active", px, None, date(2026, 6, 12))
    return facts


class _SymConn:
    """sym conn — the status + fundamentals-recency query (securities + fn CTE)."""

    def __init__(self, facts):
        self._facts = facts
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "FROM securities s" in sql and "fn AS" in sql:
            figis = set(params["f"])
            # (figi, status, fnd) per roster member in the master
            return _Cur(rows=[(f, v[0], v[3]) for f, v in self._facts.items() if f in figis])
        return _Cur()


class _EqConn:
    """equity conn — prices/returns recency (split out of the old combined CTE query)."""

    def __init__(self, facts):
        self._facts = facts
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "max(session_date) FROM prices_raw" in sql and "GROUP BY" not in sql:
            return _Cur(one=(LATEST,))
        if "min(window_id) FROM return_window" in sql:
            return _Cur(one=(1,))
        if "FROM prices_raw" in sql:  # pxd_by: (figi, max session) for priced roster members
            figis = set(params["f"])
            return _Cur(rows=[(f, v[1]) for f, v in self._facts.items()
                              if f in figis and v[1] is not None])
        if "FROM fact_returns" in sql:  # rtd_by: (figi, max as_of) for returned roster members
            figis = set(params["f"])
            return _Cur(rows=[(f, v[2]) for f, v in self._facts.items()
                              if f in figis and v[2] is not None])
        return _Cur()


class _UniConn:
    def __init__(self, roster):
        self._roster = roster

    def execute(self, sql, params=None):
        if "FROM universe_member_resolution m" in sql and "JOIN universe u" in sql:
            return _Cur(rows=self._roster)
        return _Cur()


def _gw():
    return DbSymGateway(
        _SymConn(_facts()), universe_conn=_UniConn(_roster()), equity_conn=_EqConn(_facts())
    )


def test_universe_coverage_maps_layers_and_status():
    out = _gw().universe_coverage()
    sp = next(u for u in out if u["universe_id"] == "sp500")
    assert sp["members_resolved"] == 101  # total resolved members
    assert sp["active_members"] == 100  # the delisted one is excluded from coverage
    assert sp["prices"] == {"covered": 100, "total": 100, "latest_date": "2026-06-18", "status": "ok"}
    assert sp["returns"]["status"] == "ok"
    assert sp["fundamentals"] == {"covered": 98, "total": 100, "latest_date": "2026-06-16", "status": "partial"}

    ib = next(u for u in out if u["universe_id"] == "ibov")
    assert ib["members_resolved"] == 78 and ib["active_members"] == 78
    assert ib["prices"]["status"] == "partial"  # 60/78
    assert ib["returns"] == {"covered": 0, "total": 78, "latest_date": None, "status": "missing"}
    assert ib["fundamentals"]["status"] == "ok"  # 78/78 (low-cadence: any recent counts)


def test_universe_coverage_query_is_index_bounded_not_full_table():
    # perf guard (the Overview 125s lesson): the equity-side prices/returns recency scans must
    # restrict returns to one window_id and bound by a recent date — NEVER a full-table
    # count(DISTINCT)/group-by-date. (These reads moved to the equity DB in the extraction.)
    eq = _EqConn(_facts())
    DbSymGateway(
        _SymConn(_facts()), universe_conn=_UniConn(_roster()), equity_conn=eq
    ).universe_coverage()
    rt_sql = next(s for s in eq.seen if "FROM fact_returns" in s).lower()
    px_sql = next(s for s in eq.seen if "FROM prices_raw" in s and "GROUP BY" in s).lower()
    assert "window_id = %(w)s" in rt_sql  # returns restricted to one window (not 28×)
    assert "as_of_date >= %(latest)s" in rt_sql  # bounded recent window
    assert "composite_figi = any(%(f)s)" in rt_sql  # roster-bounded, not the whole table
    assert "session_date >= %(latest)s" in px_sql  # bounded recent window
    assert "count(distinct" not in rt_sql and "count(distinct" not in px_sql


def test_universe_coverage_empty_when_no_members():
    out = DbSymGateway(_SymConn({}), universe_conn=_UniConn([])).universe_coverage()
    assert out == []
