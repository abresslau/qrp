"""FX coverage validation check (Epic FX, FX4). DB-free via a fake connection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sym.validate.fx import check_fx_coverage

AS_OF = date(2026, 6, 5)  # a Friday


class _Cur:
    def __init__(self, rows=None, one=None):
        self._rows, self._one = rows or [], one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _Conn:
    """Dispatches the three queries check_fx_coverage issues."""

    def __init__(self, needed, fx_count, rates, open_rejections=0):
        self.needed = needed          # list[str]
        self.fx_count = fx_count      # int
        self.rates = rates            # {ccy: (as_of_date, Decimal) | None}
        self.open_rejections = open_rejections

    def execute(self, sql, params=None):
        if "count(*) FROM fx.fx_rate_review" in sql:
            return _Cur(one=(self.open_rejections,))
        if "DISTINCT s.currency_code" in sql:
            return _Cur(rows=[(c,) for c in self.needed])
        if "count(*) FROM fx.fx_rate" in sql:
            return _Cur(one=(self.fx_count,))
        if "SELECT as_of_date, rate FROM fx.fx_rate" in sql:
            return _Cur(one=self.rates.get(params[0]))
        raise AssertionError(sql)


def test_empty_fx_table_warns_not_fails():
    c = _Conn(["BRL", "GBP"], 0, {})  # one fake serves both the sym + fx reads
    r = check_fx_coverage(c, c, as_of_date=AS_OF)
    assert r.status == "warn" and r.failures == 0 and r.warnings == 2


def test_missing_needed_currency_warns():
    # Coverage gaps are completeness signals -> warn (a known source limitation), not a hard
    # fail; integrity is enforced by the fx_rate constraints, not here.
    conn = _Conn(["BRL", "GBP"], 10, {"BRL": (AS_OF, Decimal("5.4")), "GBP": None})
    r = check_fx_coverage(conn, conn, as_of_date=AS_OF)
    assert r.status == "warn" and r.failures == 0 and r.warnings == 1  # GBP has no rate


def test_stale_needed_currency_warns():
    conn = _Conn(["BRL"], 10, {"BRL": (date(2026, 1, 1), Decimal("5.4"))})  # ~155d old
    r = check_fx_coverage(conn, conn, as_of_date=AS_OF)
    assert r.status == "warn" and r.warnings == 1


def test_all_fresh_passes():
    rates = {"BRL": (AS_OF, Decimal("5.4")), "GBP": (AS_OF, Decimal("0.74"))}
    c = _Conn(["BRL", "GBP"], 10, rates)
    r = check_fx_coverage(c, c, as_of_date=AS_OF)
    assert r.status == "pass" and r.failures == 0 and r.warnings == 0
