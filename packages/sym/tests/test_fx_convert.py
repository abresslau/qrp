"""FX conversion / triangulation (Epic FX, FX3b). DB-free (pure triangulate + fake conn)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sym.fx.convert import convert, triangulate
from sym.fx.resolve import FxResolution

D = date(2024, 6, 14)


def _ok(ccy, rate, obs=D):
    return FxResolution(ccy, D, Decimal(str(rate)), obs, (D - obs).days, "ok")


def test_usd_leg_single_conversion():
    # USD->BRL: 100 USD * rate(BRL)=5.4 -> 540 BRL
    assert triangulate(Decimal("100"), _ok("USD", 1), _ok("BRL", "5.4")) == Decimal("540.0")
    # BRL->USD: 540 BRL / 5.4 -> 100 USD
    assert triangulate(Decimal("540"), _ok("BRL", "5.4"), _ok("USD", 1)) == Decimal("100")


def test_cross_triangulates_through_usd():
    # BRL->JPY: amount * rate(JPY)/rate(BRL) = 100 * 160 / 5 = 3200
    assert triangulate(Decimal("100"), _ok("BRL", "5"), _ok("JPY", "160")) == Decimal("3200")


def test_either_leg_stale_or_missing_yields_none():
    stale = FxResolution("BRL", D, None, date(2024, 1, 1), 165, "stale")
    nodata = FxResolution("XYZ", D, None, None, 0, "no_data")
    assert triangulate(Decimal("100"), stale, _ok("JPY", "160")) is None
    assert triangulate(Decimal("100"), _ok("BRL", "5"), nodata) is None


def test_leg_date_spread_exceeded_yields_none():
    # BRL observed Thu, JPY observed the prior Friday (6 days apart) > weekend span -> None
    brl = _ok("BRL", "5", obs=date(2024, 6, 13))
    jpy = _ok("JPY", "160", obs=date(2024, 6, 7))
    assert triangulate(Decimal("100"), brl, jpy) is None


def test_convert_same_currency_is_identity_without_lookup():
    class _NoConn:
        def execute(self, *a, **k):  # must never be called for an identity convert
            raise AssertionError("identity convert should not query")

    assert convert(_NoConn(), 1234.5, "EUR", "EUR", D) == Decimal("1234.5")


def test_convert_accepts_int_float_str_amounts():
    class _Conn:
        def execute(self, sql, params):
            ccy = params[0]
            rate = {"BRL": Decimal("5"), "JPY": Decimal("160")}[ccy]
            return _Cur((D, rate))

    class _Cur:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    assert convert(_Conn(), 100, "BRL", "JPY", D) == Decimal("3200")
