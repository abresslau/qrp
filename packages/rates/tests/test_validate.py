"""Curve-store validation checks. DB-free (fake conn dispatched by SQL marker + params)."""

from __future__ import annotations

from datetime import date

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
    def __init__(self, latest=None, pairs=None, curves=None, prior_counts=None):
        self.latest = latest
        self.pairs = pairs or []
        self.curves = curves or {}  # {(cs,b,rt): [(tenor, value), ...]}
        self.prior_counts = prior_counts or {}  # {(cs,b): prior-day spot tenor count}

    def execute(self, sql, params=None):
        if "count(*)" in sql:  # the hole-guard prior-day count (checked before the generic SELECT)
            cs, b = params[0], params[1]
            return _Cur(one=(self.prior_counts.get((cs, b)),))
        if "max(as_of_date)" in sql:
            return _Cur(one=(self.latest,))
        if "DISTINCT curve_set, basis" in sql:
            return _Cur(all_=self.pairs)
        if "tenor, value FROM rates.curve_point" in sql:
            cs, b, rt, _asof = params
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
    conn = _Conn(latest=d, pairs=[("glc", "nominal")],
                 curves={("glc", "nominal", "spot"): [(1.0, 4.0), (2.0, 99.0)]})  # 99% impossible
    r = check_plausible_band(conn)
    assert r.status == FAIL and r.failures == 1 and "99.00% out of band" in r.samples[0]


def test_plausible_band_passes_with_negative_real_yield():
    d = date(2026, 6, 19)
    conn = _Conn(latest=d, pairs=[("glc", "real")],
                 curves={("glc", "real", "spot"): [(2.0, -0.23), (10.0, 1.1)]})  # negative is OK
    r = check_plausible_band(conn)
    assert r.status == PASS and r.failures == 0


def test_plausible_band_warns_on_a_tenor_shrink_vs_prior_day():
    d = date(2026, 6, 19)
    # latest day has 2 spot tenors but the prior published day had 80 → suspicious shrink.
    # WARN (not FAIL): BoE can legitimately trim a tenor, so it shouldn't hard-block validate.
    conn = _Conn(latest=d, pairs=[("glc", "nominal")],
                 curves={("glc", "nominal", "spot"): [(1.0, 4.0), (2.0, 4.1)]},
                 prior_counts={("glc", "nominal"): 80})
    r = check_plausible_band(conn)
    assert r.status == WARN and r.failures == 0 and any("holes" in s for s in r.samples)


def test_staleness_warns_when_old_and_handles_empty():
    # latest is a Monday; as-of two weeks later → stale warning
    conn = _Conn(latest=date(2026, 6, 1))
    r = check_staleness(conn, as_of_date=date(2026, 6, 15))
    assert r.status == WARN
    # empty store → warn, not crash
    assert check_staleness(_Conn(latest=None)).status == WARN


def test_staleness_ok_when_one_business_day():
    # Fri 2026-06-19 latest, as-of Mon 2026-06-22 → 1 business day → ok
    r = check_staleness(_Conn(latest=date(2026, 6, 19)), as_of_date=date(2026, 6, 22))
    assert r.status == PASS
