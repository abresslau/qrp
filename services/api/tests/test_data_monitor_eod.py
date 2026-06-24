"""Data Monitor › EOD — per-bucket freshness + resilient run lookup. DB-free (SQL-dispatch fakes).

Covers: ``classify`` (ok/stale/unknown + the per-bucket stale threshold), the wide-dataset
broadly-complete coverage session (the max-masks-laggards fix), the grouped worst-lagging logic
(rates per country), error-isolation (one unreadable dataset → ``unknown``, never raises), and the
best-effort Dagster run lookup degrading to ``{}`` when the endpoint is unreachable.
"""

from __future__ import annotations

from datetime import date

from lineage.buckets import BUCKETS, Dataset

from qrp_api.modules.data_monitor.eod import EodMonitorGateway
from qrp_api.modules.sym.freshness import classify


# --- classify (the shared freshness classifier the EOD page reuses) ---------------------


def test_classify_ok_within_threshold():
    f = classify("fx", date(2026, 6, 14), date(2026, 6, 16))
    assert f.status == "ok" and f.days_behind == 2


def test_classify_stale_beyond_threshold():
    f = classify("fx", date(2026, 6, 9), date(2026, 6, 16))
    assert f.status == "stale" and f.days_behind == 7


def test_classify_unknown_when_no_data():
    assert classify("fx", None, date(2026, 6, 16)).status == "unknown"


def test_classify_slow_cadence_threshold_keeps_macro_ok():
    # a 20-day-old monthly series is NOT "stale" under the macro threshold (45d), only under the
    # daily default (4d) — the per-bucket threshold is what makes the verdict honest.
    assert classify("macro", date(2026, 5, 27), date(2026, 6, 16)).status == "stale"  # default 4d
    assert classify("macro", date(2026, 5, 27), date(2026, 6, 16), stale_after_days=45).status == "ok"


# --- fake cursor/conn -------------------------------------------------------------------


class _Cur:
    def __init__(self, one=None, many=None):
        self._one, self._many = one, many

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many or []


# --- wide-dataset coverage session (max-masks-laggards fix) ------------------------------

_WIDE = Dataset("sym", "prices_raw", "session_date", "sym.prices_raw",
                wide=True, id_column="composite_figi")


class _WideConn:
    """Newest session 2026-06-16 but only 102 names priced there; the universe is broadly priced
    only through 2026-06-09 (the coverage session)."""

    def execute(self, sql, params=None):
        if "WITH per_day" in sql:
            return _Cur(one=(date(2026, 6, 9),))
        if "max(session_date)" in sql:
            return _Cur(one=(date(2026, 6, 16),))
        if "count(DISTINCT composite_figi)" in sql and "session_date = %s" in sql:
            return _Cur(one=(102,))
        raise AssertionError(f"unexpected SQL: {sql}")


def test_coverage_session_keys_off_broad_coverage_not_max():
    gw = EodMonitorGateway(_WideConn())
    actual, note = gw._coverage_session(_WideConn(), _WIDE)
    assert actual == date(2026, 6, 9)  # honest: the broadly-complete day, NOT max 06-16
    assert "102 entities at 2026-06-16" in note
    # and the bucket would read 7 days behind / stale, not "0 / ok"
    f = classify("equity_prices", actual, date(2026, 6, 16))
    assert f.days_behind == 7 and f.status == "stale"


def test_coverage_query_is_date_bounded():
    seen: list[str] = []

    class _Spy(_WideConn):
        def execute(self, sql, params=None):
            seen.append(sql)
            return super().execute(sql, params)

    EodMonitorGateway(_Spy())._coverage_session(_Spy(), _WIDE)
    cov = next(s for s in seen if "WITH per_day" in s)
    assert "session_date >=" in cov  # perf guard: bounded, not a full-table aggregate


# --- grouped worst-lagging (rates per country) ------------------------------------------

_GROUPED = Dataset("rates", "rates.curve_point", "as_of_date", "rates.curve_point",
                   group_column="country")


class _GroupConn:
    def execute(self, sql, params=None):
        return _Cur(many=[("DE", date(2026, 6, 19)), ("US", date(2026, 6, 19)),
                          ("CH", date(2025, 7, 31))])


def test_grouped_surfaces_worst_lagging_country():
    gw = EodMonitorGateway(_GroupConn())
    worst, note, subgroups = gw._grouped(_GroupConn(), _GROUPED, date(2026, 6, 19))
    assert worst == date(2025, 7, 31)  # the bucket flags on the WORST country, not the newest
    assert "2/3 current" in note and "CH" in note
    assert subgroups[0]["group"] == "CH"  # sorted worst-first


# --- error isolation: one unreadable dataset -> unknown, never raises -------------------


class _BoomConn:
    def execute(self, sql, params=None):
        raise RuntimeError("UndefinedTable")


def test_row_degrades_to_unknown_on_read_error():
    gw = EodMonitorGateway(_BoomConn())
    bucket = next(b for b in BUCKETS if b.key == "fx")  # sym-backed → uses the (boom) sym conn
    row = gw._row(bucket, date(2026, 6, 16), runs={})
    assert row["status"] == "unknown" and row["error"] is not None
    assert row["actual_date"] is None  # no fabricated date


# --- instrument count (distinct entities in the trailing window) ------------------------


class _CountConn:
    """max() returns the latest date; the windowed DISTINCT count returns a fixed N."""

    def __init__(self, count_sql_marker: str, n: int):
        self._marker, self._n, self.seen = count_sql_marker, n, []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if sql.strip().startswith("SELECT max("):
            return _Cur(one=(date(2026, 6, 16),))
        if self._marker in sql:
            return _Cur(one=(self._n,))
        raise AssertionError(f"unexpected SQL: {sql}")


def _bucket(key):
    return next(b for b in BUCKETS if b.key == key)


def test_instrument_count_is_windowed_distinct_not_single_day():
    fx = _bucket("fx")
    conn = _CountConn("count(DISTINCT quote_currency)", 28)
    n = EodMonitorGateway(conn)._instrument_count(conn, fx, fx.datasets[0])
    assert n == 28
    cnt_sql = next(s for s in conn.seen if "count(DISTINCT quote_currency)" in s)
    # perf + honesty guard: a TRAILING WINDOW (>=), never a single day (=) or a full-table scan
    assert ">=" in cnt_sql and "GROUP BY" not in cnt_sql


def test_rates_count_uses_the_composite_curve_key():
    rates = _bucket("rates")  # group_column, no single id_column → composite-key count
    conn = _CountConn("count(DISTINCT (country, curve_set, basis, rate_type))", 36)
    n = EodMonitorGateway(conn)._instrument_count(conn, rates, rates.datasets[0])
    assert n == 36


def test_count_none_for_buckets_without_a_count_basis():
    # calculations + universe carry no id_column (the fact_returns full-table-distinct perf trap /
    # event-log) → no instrument count, never a fabricated number.
    for key in ("calculations", "universe"):
        b = _bucket(key)
        # a conn whose only answer is max(); if a count query were issued it would AssertionError
        conn = _CountConn("__never__", 0)
        assert EodMonitorGateway(conn)._instrument_count(conn, b, b.datasets[0]) is None


def test_commodities_is_a_bucket_but_not_a_generated_dagster_job():
    from lineage.bucket_jobs import BUCKET_JOBS, _EXTERNAL_JOB_BUCKETS
    from lineage.buckets import bucket_keys

    assert "commodities" in bucket_keys()  # on the EOD board
    cb = _bucket("commodities")
    assert cb.datasets[0].wide and cb.datasets[0].id_column == "commodity_code"
    # collision guard: the dedicated `commodities` job (schedules.py) owns the name — no duplicate
    assert "commodities" in _EXTERNAL_JOB_BUCKETS
    assert len(BUCKET_JOBS) == len(bucket_keys()) - 1


# --- best-effort Dagster run lookup -----------------------------------------------------


def test_latest_runs_empty_when_endpoint_unreachable(monkeypatch):
    import qrp_api.modules.data_monitor.dagster_runs as dr

    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(dr.urllib.request, "urlopen", _boom)
    assert dr.latest_runs_by_job(timeout=0.1) == (False, {})  # not reachable, degrades, never raises
