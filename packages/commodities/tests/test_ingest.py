"""fill_prices upsert logic — DB-free (fake conn dispatched by SQL marker)."""

from __future__ import annotations

from datetime import date

from commodities.ingest import fill_prices
from commodities.sources.base import PricePoint


class _Txn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Cur:
    def __init__(self, one=None, all_=None):
        self._one, self._all = one, all_ or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    """Records INSERTs; simulates a fresh insert (xmax=0 → True). No prev rows (band disabled)."""

    def __init__(self):
        self.inserts: list[dict] = []

    def transaction(self):
        return _Txn()

    def execute(self, sql, params=None):
        if "INSERT INTO commodities.price_daily" in sql:
            self.inserts.append(params)
            return _Cur(one=(True,))
        if "DISTINCT ON" in sql:  # plausibility seed (only when band enabled)
            return _Cur(all_=[])
        return _Cur(one=None)


class _Src:
    SOURCE = "test"

    def __init__(self, pts):
        self._pts = pts

    def fetch(self, *, start_date=None, end_date=None):
        return self._pts


def test_fill_inserts_and_sets_first_settle_to_settle():
    pts = [
        PricePoint("WTI", "continuous_front", date(2026, 6, 22), 73.1, volume=100.0),
        PricePoint("WTI", "continuous_front", date(2026, 6, 23), 73.05, volume=120.0),
        PricePoint("GOLD", "continuous_front", date(2026, 6, 23), 4129.0),
    ]
    conn = _Conn()
    s = fill_prices(conn, _Src(pts))
    assert s.inserted == 3 and s.restated == 0 and s.flagged == 0
    assert s.days == 2  # two distinct as_of_dates
    assert s.codes == ["GOLD", "WTI"]
    # first_settle is bound to the same %(s)s param as settle → immutable PIT value == settle
    assert all(p["s"] is not None for p in conn.inserts)


def test_band_routes_outlier_to_review(monkeypatch):
    # seed prev via a conn that returns a prior settle, then feed a >50% move
    class _BandConn(_Conn):
        def execute(self, sql, params=None):
            if "DISTINCT ON" in sql:
                return _Cur(all_=[("WTI", "continuous_front", 100.0)])
            if "INSERT INTO commodities.price_review" in sql:
                self.inserts.append({"review": params})
                return _Cur(one=None)
            return super().execute(sql, params)

    conn = _BandConn()
    pts = [PricePoint("WTI", "continuous_front", date(2026, 6, 23), 10.0)]  # 100 -> 10 = -90%
    s = fill_prices(conn, _Src(pts), band_pct=0.5)
    assert s.flagged == 1 and s.inserted == 0
