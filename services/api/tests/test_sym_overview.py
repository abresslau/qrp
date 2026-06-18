"""Overview freshness — honest prices coverage (the max-is-fresh-masks-laggards fix).

Covers `classify` (ok/stale/unknown + coverage passthrough) and `gateway.overview()` keying
the prices area off the BROAD-coverage session, not max(session_date), so a fresh sub-universe
no longer makes prices report "0 days behind / ok" while the rest of the universe is stale.
DB-free — SQL-dispatching fake conn.
"""

from __future__ import annotations

from datetime import date

from qrp_api.modules.sym.freshness import classify
from qrp_api.modules.sym.gateway import DbSymGateway


# --- classify ---------------------------------------------------------------------------


def test_classify_ok_within_threshold():
    f = classify("prices", date(2026, 6, 14), date(2026, 6, 16))
    assert f.status == "ok" and f.days_behind == 2


def test_classify_stale_beyond_threshold_and_passes_coverage():
    f = classify("prices", date(2026, 6, 9), date(2026, 6, 16), coverage="102/2145 at 2026-06-16")
    assert f.status == "stale" and f.days_behind == 7
    assert f.coverage == "102/2145 at 2026-06-16"


def test_classify_unknown_when_no_data():
    assert classify("fx", None, date(2026, 6, 16)).status == "unknown"


# --- gateway.overview() honest prices freshness -----------------------------------------


class _Cur:
    def __init__(self, one):
        self._one = one

    def fetchone(self):
        return self._one


class _OverviewConn:
    """Returns canned scalars for each overview query — the stale-coverage scenario:
    newest session 2026-06-16 but only 102 names priced there; the universe is broadly
    priced through 2026-06-09 (the coverage session)."""

    def __init__(self):
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "EXISTS (SELECT 1 FROM prices_raw" in sql:  # priced (must precede the securities count)
            return _Cur((2145,))
        if "count(*) FROM securities" in sql:
            return _Cur((2145,))
        if "count(*) FROM universe" in sql:
            return _Cur((15,))
        if "WHERE session_date = %s" in sql:  # priced_at_latest (must precede the bare prices count)
            return _Cur((102,))
        if "count(DISTINCT composite_figi) FROM prices_raw" in sql:
            return _Cur((2145,))  # (no longer used by priced; kept for any other distinct-count)
        if "WITH per_day" in sql:  # broad-coverage session
            return _Cur((date(2026, 6, 9),))
        if "max(session_date) FROM prices_raw" in sql:  # latest_session
            return _Cur((date(2026, 6, 16),))
        if "FROM fact_returns" in sql:
            return _Cur((date(2026, 6, 16),))
        if "FROM fx_rate" in sql:
            return _Cur((date(2026, 6, 9),))
        if "FROM fundamentals" in sql:
            return _Cur((date(2026, 6, 16),))
        if "FROM pipeline_run_log" in sql:
            return _Cur(None)  # no last run
        raise AssertionError(f"unexpected SQL: {sql}")


def test_coverage_query_is_bounded_to_recent_history_not_full_table():
    # perf guard: the per-day count(DISTINCT) coverage scan MUST be date-bounded — over the
    # full 13M-row prices_raw it took 125s (Overview timed out). Bounding to recent sessions
    # drops it to ~1.5s. Regression for that.
    conn = _OverviewConn()
    DbSymGateway(conn).overview()
    cov_sql = next(s for s in conn.seen if "WITH per_day" in s)
    assert "session_date >=" in cov_sql  # bounded, not a full-table aggregate


def test_overview_prices_freshness_keys_off_broad_coverage_not_max():
    o = DbSymGateway(_OverviewConn()).overview()

    assert o.latest_session == date(2026, 6, 16)
    assert o.priced_at_latest == 102  # the honest coverage gap (vs 2145 priced ever)

    prices = next(f for f in o.freshness if f.area == "prices")
    # the bug was: prices compared max-to-max → always 0 behind / ok. Now it keys off the
    # broad-coverage session (06-09), so it honestly reports 7 days behind / stale.
    assert prices.as_of_date == date(2026, 6, 9)
    assert prices.days_behind == 7
    assert prices.status == "stale"
    assert prices.coverage == "102/2145 at 2026-06-16"


def test_overview_prices_ok_when_universe_broadly_current():
    # control: when coverage_session == latest_session (full universe loaded), prices is ok
    class _FreshConn(_OverviewConn):
        def execute(self, sql, params=None):
            if "WITH per_day" in sql:
                return _Cur((date(2026, 6, 16),))  # broadly current
            if "WHERE session_date = %s" in sql:
                return _Cur((2140,))
            return super().execute(sql, params)

    o = DbSymGateway(_FreshConn()).overview()
    prices = next(f for f in o.freshness if f.area == "prices")
    assert prices.days_behind == 0 and prices.status == "ok"
