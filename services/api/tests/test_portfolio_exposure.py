"""Portfolio net/gross exposure (computed in gateway.get() from the shown vector). DB-free."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from portfolios.gateway import DbPortfolioGateway


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    """Routes get()'s three reads: meta, distinct as-of dates, the weight vector."""

    autocommit = False

    def __init__(self, weights, dates=(date(2026, 6, 5),)):
        self._weights = weights  # [(figi, Decimal weight), ...]
        self._dates = list(dates)

    def execute(self, sql, params=None):
        if "FROM portfolios.portfolio p" in sql:
            return _Cur(one=(7, "Book", "Acme", "USD", None, None))
        if "DISTINCT as_of_date" in sql:
            return _Cur(rows=[(d,) for d in self._dates])
        if "composite_figi, weight" in sql:
            return _Cur(rows=list(self._weights))
        return _Cur()


def _gw(weights, dates=(date(2026, 6, 5),)):
    return DbPortfolioGateway(_Conn(weights, dates))  # sym_conn=None → labels skipped


def test_long_only_net_equals_gross():
    d = _gw([("F1", Decimal("0.5")), ("F2", Decimal("0.3")), ("F3", Decimal("0.2"))]).get(7)
    assert d["net_exposure"] == 1.0
    assert d["gross_exposure"] == 1.0  # no shorts → net == gross


def test_long_short_gross_exceeds_net():
    # 130/30-ish: longs 0.6+0.5, short -0.1 → net 1.0, gross 1.2
    d = _gw([("F1", Decimal("0.6")), ("F2", Decimal("0.5")), ("F3", Decimal("-0.1"))]).get(7)
    assert d["net_exposure"] == 1.0
    assert round(d["gross_exposure"], 6) == 1.2  # the |short| adds to gross, not net


def test_no_vector_exposures_are_null():
    d = _gw([], dates=()).get(7)  # no stored vector
    assert d["shown_as_of_date"] is None
    assert d["net_exposure"] is None and d["gross_exposure"] is None
