"""Derived market cap (Epic FX consumer). DB-free via a fake connection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sym.marketcap import market_cap

D = date(2026, 6, 5)


class _Cur:
    def __init__(self, one):
        self._one = one

    def fetchone(self):
        return self._one


class _Conn:
    """Dispatches the queries market_cap / convert issue."""

    def __init__(self, *, local, close_raw, shares, shares_as_of_date, fx=None):
        self.local, self.close_raw = local, close_raw
        self.shares, self.shares_as_of_date = shares, shares_as_of_date
        self.fx = fx or {}  # {ccy: rate_per_usd} for convert's resolver

    def execute(self, sql, params=None):
        if "FROM securities" in sql:
            return _Cur((self.local,) if self.local else None)
        if "FROM v_prices_adjusted" in sql:
            # (close_raw, session_date) — the date feeds the staleness bound; the fake
            # prices on the as-of date itself (params[1]) so existing tests stay fresh.
            return _Cur((self.close_raw, params[1]) if self.close_raw is not None else None)
        if "FROM fundamentals" in sql:
            return _Cur((self.shares, self.shares_as_of_date) if self.shares is not None else None)
        if "SELECT as_of_date, rate FROM fx.fx_rate" in sql:  # convert -> fx_rate resolver (fx DB)
            ccy = params[0]
            r = self.fx.get(ccy)
            return _Cur((D, r) if r is not None else None)
        raise AssertionError(sql)


def test_lcy_market_cap_is_price_times_shares():
    # USD stock: 268.94 x 536,376,000 = 144,247,... ; ccy=None -> LCY (=USD here)
    conn = _Conn(local="USD", close_raw=Decimal("268.94"), shares=Decimal("536376000"),
                 shares_as_of_date=date(2026, 5, 1))
    mc = market_cap(conn, conn, "BBG", D)
    assert mc.currency == "USD"
    assert mc.value == Decimal("268.94") * Decimal("536376000")
    assert mc.shares_as_of_date == date(2026, 5, 1)  # forward-filled report date exposed


def test_local_cap_then_converted_to_usd():
    # A BRL stock: mcap_lcy = 10 x 1,000,000 = 10,000,000 BRL; USD = / 5.0 = 2,000,000
    conn = _Conn(local="BRL", close_raw=Decimal("10"), shares=Decimal("1000000"),
                 shares_as_of_date=D, fx={"BRL": Decimal("5.0")})
    lcy = market_cap(conn, conn, "BBG", D)            # LCY
    usd = market_cap(conn, conn, "BBG", D, "USD")     # restated
    assert lcy.value == Decimal("10000000") and lcy.currency == "BRL"
    assert usd.value == Decimal("2000000") and usd.currency == "USD"


def test_missing_price_or_shares_yields_none_value():
    no_px = _Conn(local="USD", close_raw=None, shares=Decimal("100"), shares_as_of_date=D)
    no_sh = _Conn(local="USD", close_raw=Decimal("10"), shares=None, shares_as_of_date=None)
    assert market_cap(no_px, no_px, "BBG", D).value is None
    assert market_cap(no_sh, no_sh, "BBG", D).value is None


def test_missing_fx_leg_yields_none_value_but_keeps_inputs():
    conn = _Conn(local="BRL", close_raw=Decimal("10"), shares=Decimal("100"),
                 shares_as_of_date=D, fx={})  # no BRL rate -> convert returns None
    mc = market_cap(conn, conn, "BBG", D, "USD")
    assert mc.value is None and mc.close_raw == Decimal("10") and mc.shares == Decimal("100")
