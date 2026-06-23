"""Curve-store validation checks. DB-free (fake conn dispatched by SQL marker + params)."""

from __future__ import annotations

from datetime import date, timedelta

from rates.validate import (
    FAIL,
    PASS,
    WARN,
    check_inflation_reconcile,
    check_plausible_band,
    check_staleness,
)


class _Cur:
    def __init__(self, one=None, all_=None):
        self._one, self._all = one, all_ or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    def __init__(self, latest=None, recent=None, series=None, curves=None, prior_counts=None):
        self.latest = latest
        self.recent = recent  # DESC list of distinct dates (for staleness cadence)
        self.series = series or []  # [(cs, b, rt), ...] present on the latest date
        self.curves = curves or {}  # {(cs,b,rt): [(tenor, value), ...]}
        self.prior_counts = prior_counts or {}  # {(cs,b,rt): prior-day tenor count}

    def execute(self, sql, params=None):
        if "count(*)" in sql:  # hole-guard prior-day count; params=(co,cs,b,rt,co,cs,b,rt,latest)
            cs, b, rt = params[1], params[2], params[3]
            return _Cur(one=(self.prior_counts.get((cs, b, rt)),))
        if "DISTINCT as_of_date" in sql:  # staleness recent-dates window
            return _Cur(all_=[(d,) for d in (self.recent or [])])
        if "max(as_of_date)" in sql:
            return _Cur(one=(self.latest,))
        if "DISTINCT curve_set, basis, rate_type" in sql:
            return _Cur(all_=self.series)
        if "tenor, value FROM rates.curve_point" in sql:  # params=(co,cs,b,rt,asof)
            _co, cs, b, rt, _asof = params
            return _Cur(all_=self.curves.get((cs, b, rt), []))
        return _Cur()


def test_inflation_reconcile_passes_when_inflation_equals_nominal_minus_real():
    d = date(2026, 6, 19)
    conn = _Conn(latest=d, curves={
        ("glc", "nominal", "spot"): [(2.0, 4.00), (5.0, 4.20)],
        ("glc", "real", "spot"): [(2.0, 1.00), (5.0, 0.80)],
        ("glc", "inflation", "spot"): [(2.0, 3.00), (5.0, 3.40)],  # == nominal - real
    })
    r = check_inflation_reconcile(conn)
    assert r.status == PASS and r.checked == 2 and r.failures == 0


def test_inflation_reconcile_fails_on_mismatch():
    d = date(2026, 6, 19)
    conn = _Conn(latest=d, curves={
        ("glc", "nominal", "spot"): [(2.0, 4.00)],
        ("glc", "real", "spot"): [(2.0, 1.00)],
        ("glc", "inflation", "spot"): [(2.0, 3.50)],  # should be 3.00 → 0.50pp off
    })
    r = check_inflation_reconcile(conn)
    assert r.status == FAIL and r.failures == 1
    assert "delta 0.500pp" in r.samples[0]


def test_inflation_reconcile_skips_when_no_real_curve():
    conn = _Conn(latest=date(2026, 6, 19), curves={("glc", "nominal", "spot"): [(2.0, 4.0)]})
    r = check_inflation_reconcile(conn)
    assert r.status == WARN and r.checked == 0  # skipped, not a false FAIL


def test_plausible_band_fails_out_of_band():
    d = date(2026, 6, 19)
    conn = _Conn(latest=d, series=[("glc", "nominal", "spot")],
                 curves={("glc", "nominal", "spot"): [(1.0, 4.0), (2.0, 99.0)]})  # 99% impossible
    r = check_plausible_band(conn, "GB")
    assert r.status == FAIL and r.failures == 1 and "99.00% out of band" in r.samples[0]


def test_plausible_band_passes_with_negative_real_yield():
    d = date(2026, 6, 19)
    conn = _Conn(latest=d, series=[("glc", "real", "spot")],
                 curves={("glc", "real", "spot"): [(2.0, -0.23), (10.0, 1.1)]})  # negative is OK
    r = check_plausible_band(conn, "GB")
    assert r.status == PASS and r.failures == 0


def test_plausible_band_warns_on_a_tenor_shrink_vs_prior_day():
    d = date(2026, 6, 19)
    # latest day has 2 tenors but the prior published day had 80 → suspicious shrink → WARN.
    conn = _Conn(latest=d, series=[("glc", "nominal", "spot")],
                 curves={("glc", "nominal", "spot"): [(1.0, 4.0), (2.0, 4.1)]},
                 prior_counts={("glc", "nominal", "spot"): 80})
    r = check_plausible_band(conn, "GB")
    assert r.status == WARN and r.failures == 0 and any("holes" in s for s in r.samples)


def _daily(latest: date, n: int = 10) -> list[date]:
    # a DESC run of weekday-ish daily dates ending at `latest` (cadence ~1d)
    return [latest - timedelta(days=i) for i in range(n)]


def test_staleness_warns_when_old_and_handles_empty():
    # daily cadence, latest two weeks before as-of → stale warning
    conn = _Conn(recent=_daily(date(2026, 6, 1)))
    r = check_staleness(conn, "GB", as_of_date=date(2026, 6, 15))
    assert r.status == WARN
    # empty store → warn, not crash
    assert check_staleness(_Conn(recent=[]), "GB").status == WARN


def test_staleness_ok_when_recent_vs_cadence():
    # Fri 2026-06-19 latest (daily cadence), as-of Mon 2026-06-22 → 3d ≤ ~5d grace → ok
    r = check_staleness(_Conn(recent=_daily(date(2026, 6, 19))), "GB", as_of_date=date(2026, 6, 22))
    assert r.status == PASS


def test_staleness_monthly_series_not_flagged():
    # monthly cadence (ECB 10y): latest 5 weeks before as-of is within the scaled grace, not stale
    monthly = [date(2026, 5, 1) - timedelta(days=30 * i) for i in range(10)]
    r = check_staleness(_Conn(recent=monthly), "FR", as_of_date=date(2026, 6, 5))
    assert r.status == PASS
