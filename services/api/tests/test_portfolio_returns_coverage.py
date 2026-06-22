"""Portfolio returns snapshot pins to the latest BROADLY-COMPLETE date, not the bare max.

Regression for the bug where `gateway.returns()` pinned every constituent to
max(as_of_date) — a sparse "today" only the already-closed markets reach — dropping every
name whose latest session was a day behind (portfolio 3 showed 18/100 instead of 100/100).
DB-free: routed fake conns for the qrp + sym connections.
"""

from __future__ import annotations

from datetime import date

from portfolios.gateway import DbPortfolioGateway


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _QrpConn:
    autocommit = False

    def __init__(self, weights):
        self._weights = weights  # [(figi, weight)]

    def execute(self, sql, params=None):
        if "max(as_of_date) FROM portfolios.portfolio_weight" in sql:
            return _Cur(one=(date(2026, 6, 1),))
        if "composite_figi, weight FROM portfolios.portfolio_weight" in sql:
            return _Cur(rows=list(self._weights))
        return _Cur()


class _SymConn:
    def __init__(self, ret_date, pr_rows):
        self._ret_date = ret_date
        self._pr = pr_rows
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "FROM return_window WHERE code" in sql:
            return _Cur(one=(1, "YTD"))
        if "WITH per_day" in sql:  # the broadly-complete-date pick (the fix)
            return _Cur(one=(self._ret_date,))
        if "FROM fact_returns" in sql and "as_of_date = %s" in sql:
            return _Cur(rows=list(self._pr))
        if "FROM security_symbology" in sql:
            return _Cur(rows=[])  # labels optional; ticker defaults to figi
        if "FROM security_names" in sql:
            return _Cur(rows=[])
        return _Cur()


def test_returns_pins_to_broadly_complete_date_and_covers_all_members():
    weights = [("F1", 0.5), ("F2", 0.3), ("F3", 0.2)]
    # broadly-complete date is 2026-06-17; ALL three members have a row there
    sym = _SymConn(date(2026, 6, 17), [("F1", 0.10), ("F2", 0.20), ("F3", -0.05)])
    gw = DbPortfolioGateway(_QrpConn(weights), sym)
    out = gw.returns(3, "YTD")

    assert out["returns_as_of_date"] == "2026-06-17"  # NOT a sparse later max
    assert out["n_with_return"] == 3  # every member covered, not just the latest-session one
    assert out["n_constituents"] == 3
    assert round(out["portfolio_return"], 4) == round(0.5 * 0.10 + 0.3 * 0.20 + 0.2 * -0.05, 4)


def test_returns_uses_broadly_complete_query_not_bare_max():
    # perf+correctness guard: the ret-date selection must be the per_day/>=0.9 form, never the
    # bare `max(as_of_date) FROM fact_returns` that caused the sparse-today drop.
    sym = _SymConn(date(2026, 6, 17), [("F1", 0.1)])
    DbPortfolioGateway(_QrpConn([("F1", 1.0)]), sym).returns(3, "YTD")
    retdate_sql = next(s for s in sym.seen if "WITH per_day" in s)
    assert "0.9" in retdate_sql  # broadly-complete threshold, not bare max


def test_returns_skips_gated_null_pr_when_pinning_and_looking_up():
    # AR-9 gating guard: both the date pin (per_day CTE) and the pr lookup must filter `pr IS NOT NULL`,
    # so an all-gated latest date can't win the pin and leave 97/100 constituents null (the YTD-top-movers
    # bug). SQL-level behaviour — asserted on the issued SQL, like the broadly-complete guard above.
    sym = _SymConn(date(2026, 6, 17), [("F1", 0.1)])
    DbPortfolioGateway(_QrpConn([("F1", 1.0)]), sym).returns(3, "YTD")
    per_day_sql = next(s for s in sym.seen if "WITH per_day" in s)
    lookup_sql = next(s for s in sym.seen if "FROM fact_returns" in s and "as_of_date = %s" in s)
    assert "pr IS NOT NULL" in per_day_sql  # gated rows don't win the date pin
    assert "pr IS NOT NULL" in lookup_sql   # nor populate the constituent map
