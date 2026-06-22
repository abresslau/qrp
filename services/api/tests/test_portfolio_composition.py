"""Live portfolio composition — the heat-map (sized by position size) + sector/position donut
surface (story portfolios-live-heatmap-and-pizza). DB-free: the portfolios seam is monkeypatched,
the sym conn is faked, the quote fan-out is monkeypatched. Asserts the per-holding cell shape with
SIGNED weights preserved, the per-sector |weight| rollup (slice size + weighted live return), the
honest freshness/coverage roll-up, the writes-nothing property, and the 404/422/503 mappings.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from analytics import gateway as gw_mod
from analytics import quotes
from analytics import router as router_mod
from analytics.gateway import DbAnalyticsGateway
from analytics.quotes import QuoteSourceUnreachable, RawQuote


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _SymConn:
    """Fake sym read conn — dispatches by SQL: the ``fact_returns`` window-returns query gets
    ``ret_rows`` ((figi, code, pr) tuples), the ``fact_price_extremes`` query gets ``ext_rows``
    ((figi, low_52w, high_52w) tuples), every other query gets the meta ``rows``. RECORDS the SQL
    it sees so a test can assert the live path issues no INSERT/UPDATE."""

    def __init__(self, rows, ret_rows=None, ext_rows=None):
        self._rows = rows
        self._ret_rows = ret_rows or []
        self._ext_rows = ext_rows or []
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "fact_price_extremes" in sql:
            return _Cur(self._ext_rows)
        if "fact_returns" in sql:
            return _Cur(self._ret_rows)
        # The meta SELECT now also returns country_iso/exch_code/bbg_exchange_code (the qualified-ticker
        # codes). These fixtures only care about weights/returns/sectors, so right-pad each row with None
        # for the trailing code columns rather than restate all of them. (Column-count drift is guarded by
        # the explorer/securities + ticker unit tests; these composition tests assert logic, not shape.)
        meta_cols = 15
        return _Cur([tuple(r) + (None,) * (meta_cols - len(r)) if len(r) < meta_cols else r for r in self._rows])


def _wire(monkeypatch, *, weights, exists=True):
    monkeypatch.setattr(gw_mod, "portfolio_exists", lambda conn, pid: exists)
    monkeypatch.setattr(gw_mod, "read_latest_weights", lambda conn, pid: (date(2026, 6, 1), weights))


_EPOCH = 1781553601


def test_composition_assembly_signed_weight_and_sector_rollup(monkeypatch):
    # One long (priced) IT name + one short (uncovered) Energy name.
    _wire(monkeypatch, weights={"F1": Decimal("0.6"), "F2": Decimal("-0.2")})
    # row shape: figi, ticker, mic, sector, industry, name, currency, status, mcap, country, volume, last_close
    sym = _SymConn([
        ("F1", "AAPL", "XNAS", "Information Technology", "Tech HW", "Apple Inc", "USD", "active", 3.0e12, "United States", 50_000_000, 100.0),
        ("F2", "PETR4", "BVMF", "Energy", "Oil & Gas", "Petrobras", "BRL", "active", 1.0e11, "Brazil", 2_000_000, 30.0),
    ])

    def fake_batch(symbols, **kw):
        return {
            "AAPL": RawQuote(price=110.0, prev_close=100.0, currency="USD", quote_epoch=_EPOCH),
            "PETR4.SA": None,  # reachable, no data -> uncovered
        }

    monkeypatch.setattr(quotes, "fetch_quotes_batch", fake_batch)
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH + 10)

    assert out["n_holdings"] == 2 and out["n_priced"] == 1
    assert out["total_weight"] == pytest.approx(0.8)   # |0.6| + |-0.2|
    assert out["net_weight"] == pytest.approx(0.4)     # 0.6 + (-0.2)
    assert out["freshness"] == "live"
    assert out["as_of"] == datetime.fromtimestamp(_EPOCH, tz=timezone.utc).isoformat()

    # holdings sorted by position SIZE (|weight|) desc: F1 (0.6) before F2 (0.2)
    h0, h1 = out["holdings"]
    assert h0["figi"] == "F1"
    assert h0["weight"] == pytest.approx(0.6) and h0["live_return"] == pytest.approx(0.10)
    assert h0["sector"] == "Information Technology" and h0["name"] == "Apple Inc"
    assert h0["freshness"] == "live" and h0["price"] == pytest.approx(110.0)
    # explorer-style enrichment fields carried through
    assert h0["mic"] == "XNAS" and h0["country"] == "United States" and h0["status"] == "active"
    assert h0["market_cap_usd"] == pytest.approx(3.0e12) and h0["volume"] == 50_000_000
    assert h1["figi"] == "F2"
    assert h1["weight"] == pytest.approx(-0.2)          # SIGN preserved (short)
    assert h1["live_return"] is None and h1["freshness"] == "unavailable"

    # sector slices: Σ|weight| per sector, summing to gross; uncovered sector return is None
    secs = {s["sector"]: s for s in out["sectors"]}
    assert secs["Information Technology"]["weight"] == pytest.approx(0.6)
    assert secs["Information Technology"]["live_return"] == pytest.approx(0.10)
    assert secs["Energy"]["weight"] == pytest.approx(0.2)
    assert secs["Energy"]["live_return"] is None
    assert sum(s["weight"] for s in out["sectors"]) == pytest.approx(out["total_weight"])


def test_composition_sector_return_is_weight_weighted(monkeypatch):
    # Two priced holdings in ONE sector with different returns -> |weight|-weighted rollup.
    _wire(monkeypatch, weights={"F1": Decimal("0.6"), "F3": Decimal("0.4")})
    sym = _SymConn([
        ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, None),
        ("F3", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD", None, None, None, None, None),
    ])
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {
        "AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH),   # +10%
        "MSFT": RawQuote(120.0, 100.0, "USD", _EPOCH),   # +20%
    })
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    tech = next(s for s in out["sectors"] if s["sector"] == "Tech")
    # (0.6*0.10 + 0.4*0.20) / (0.6 + 0.4) = 0.14
    assert tech["live_return"] == pytest.approx(0.14)


def test_composition_window_returns_rebased_to_live(monkeypatch):
    # F1 priced (last_close 100), F2 unpriced (no quote), F3 priced but last_close missing.
    _wire(monkeypatch, weights={
        "F1": Decimal("0.5"), "F2": Decimal("0.3"), "F3": Decimal("0.2"),
    })
    sym = _SymConn(
        [
            ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, 100.0),
            ("F2", "ZZZ", "XNAS", "Tech", None, "Zed", "USD", None, None, None, None, 50.0),
            ("F3", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD", None, None, None, None, None),
        ],
        # (figi, window code, pr) — already deduped (the latest-as_of pick is the SQL's DISTINCT ON,
        # which this fake conn can't exercise; it's an integration concern, not a unit one).
        ret_rows=[
            ("F1", "1D", 0.01), ("F1", "1M", 0.10), ("F1", "3M", 0.30),  # no 6M for F1
            ("F2", "1M", 0.05),
            ("F3", "1M", 0.20),
        ],
    )
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {
        "AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH),   # priced
        "MSFT": RawQuote(120.0, 100.0, "USD", _EPOCH),   # priced (F3)
        # ZZZ absent -> F2 unpriced
    })
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    by = {h["figi"]: h for h in out["holdings"]}

    # F1 priced -> each window re-based to the live price: price*(1+pr)/last_close - 1
    assert set(by["F1"]["window_returns"]) == {"1D", "1M", "3M", "6M", "MTD", "YTD"}  # all keys present
    assert by["F1"]["window_returns"]["1D"] == pytest.approx(110 * 1.01 / 100 - 1)   # 0.111
    assert by["F1"]["window_returns"]["1M"] == pytest.approx(0.21)                   # 110*1.10/100-1
    assert by["F1"]["window_returns"]["3M"] == pytest.approx(0.43)                   # 110*1.30/100-1
    assert by["F1"]["window_returns"]["6M"] is None                                  # no stored pr

    # F2 NOT priced live -> degrade to the plain stored EOD return (no re-base)
    assert by["F2"]["live_return"] is None
    assert by["F2"]["window_returns"]["1M"] == pytest.approx(0.05)
    assert by["F2"]["window_returns"]["1D"] is None and by["F2"]["window_returns"]["6M"] is None

    # F3 priced but last_close missing -> not computable -> null even with a stored pr
    assert by["F3"]["live_return"] == pytest.approx(0.20)
    assert by["F3"]["window_returns"]["1M"] is None


def test_composition_52w_range_positions_the_current_price(monkeypatch):
    # F1 priced live (uses the live price within the range); F2 unpriced (uses last_close);
    # F3 has no extremes row (range fields null); F4 has a degenerate range (low == high -> null).
    _wire(monkeypatch, weights={
        "F1": Decimal("0.4"), "F2": Decimal("0.3"), "F3": Decimal("0.2"), "F4": Decimal("0.1"),
    })
    sym = _SymConn(
        [
            ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, 100.0),
            ("F2", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD", None, None, None, None, 60.0),
            ("F3", "GOOG", "XNAS", "Tech", None, "Alphabet", "USD", None, None, None, None, 50.0),
            ("F4", "ZZZ", "XNAS", "Tech", None, "Zed", "USD", None, None, None, None, 80.0),
        ],
        # (figi, low_52w, high_52w) — F3 omitted (no row); F4 degenerate.
        ext_rows=[
            ("F1", Decimal("50"), Decimal("150")),
            ("F2", Decimal("40"), Decimal("80")),
            ("F4", Decimal("80"), Decimal("80")),
        ],
    )
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {
        "AAPL": RawQuote(125.0, 100.0, "USD", _EPOCH),  # F1 priced live at 125
        # MSFT absent -> F2 unpriced (falls back to last_close 60)
    })
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    by = {h["figi"]: h for h in out["holdings"]}

    # F1: live price 125 in [50, 150] -> (125-50)/100 = 0.75
    assert by["F1"]["low_52w"] == pytest.approx(50.0) and by["F1"]["high_52w"] == pytest.approx(150.0)
    assert by["F1"]["range_pct"] == pytest.approx(0.75)
    # F2: not priced live -> last_close 60 in [40, 80] -> (60-40)/40 = 0.5
    assert by["F2"]["range_pct"] == pytest.approx(0.5)
    # F3: no extremes row -> all three fields null
    assert by["F3"]["low_52w"] is None and by["F3"]["high_52w"] is None and by["F3"]["range_pct"] is None
    # F4: degenerate range (high == low) -> range_pct null (no divide-by-zero)
    assert by["F4"]["range_pct"] is None


def test_composition_52w_range_clamps_a_fresh_live_high(monkeypatch):
    # A live print above the close-based 52w high clamps to 1.0 (a full bar, never overflow).
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn(
        [("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, 100.0)],
        ext_rows=[("F1", Decimal("50"), Decimal("120"))],
    )
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {
        "AAPL": RawQuote(130.0, 100.0, "USD", _EPOCH),  # 130 > 120 high -> clamp to 1.0
    })
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    assert out["holdings"][0]["range_pct"] == pytest.approx(1.0)


def test_composition_window_returns_guard_nonfinite_base(monkeypatch):
    # Re-base inputs that are unusable must yield null, never a garbage/non-finite value (which would
    # break JSON serialization). F1: negative last_close; F2: NaN last_close; F3: NaN stored pr.
    nan = float("nan")
    _wire(monkeypatch, weights={
        "F1": Decimal("0.4"), "F2": Decimal("0.3"), "F3": Decimal("0.3"),
    })
    sym = _SymConn(
        [
            ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, -5.0),
            ("F2", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD", None, None, None, None, nan),
            ("F3", "GOOG", "XNAS", "Tech", None, "Alphabet", "USD", None, None, None, None, 100.0),
        ],
        ret_rows=[("F1", "1M", 0.1), ("F2", "1M", 0.1), ("F3", "1M", nan)],
    )
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {
        "AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH),
        "MSFT": RawQuote(120.0, 100.0, "USD", _EPOCH),
        "GOOG": RawQuote(130.0, 100.0, "USD", _EPOCH),
    })
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    by = {h["figi"]: h for h in out["holdings"]}
    assert by["F1"]["window_returns"]["1M"] is None   # negative base -> null
    assert by["F2"]["window_returns"]["1M"] is None   # NaN base -> null
    assert by["F3"]["window_returns"]["1M"] is None   # NaN pr -> null
    # nothing non-finite leaked into any cell
    import math as _m
    for h in out["holdings"]:
        for v in h["window_returns"].values():
            assert v is None or _m.isfinite(v)


def test_composition_unmapped_mic_is_unavailable(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn([("F1", "FOO", "XZZZ", "Unclassified", None, "Foo Co", None, None, None, None, None, None)])  # XZZZ unmapped
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {})
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    assert out["n_priced"] == 0 and out["freshness"] == "unavailable"
    assert out["holdings"][0]["live_return"] is None
    assert out["holdings"][0]["freshness"] == "unavailable"


def test_composition_all_unreachable_raises(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("0.5"), "F2": Decimal("0.5")})
    sym = _SymConn([
        ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, None),
        ("F2", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD", None, None, None, None, None),
    ])

    def boom(symbols, **kw):
        raise QuoteSourceUnreachable("down")

    monkeypatch.setattr(quotes, "fetch_quotes_batch", boom)
    with pytest.raises(QuoteSourceUnreachable):
        DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)


def test_composition_no_weights_is_empty(monkeypatch):
    _wire(monkeypatch, weights={})
    out = DbAnalyticsGateway(conn=object(), sym_conn=_SymConn([])).composition(1, now=_EPOCH)
    assert out["n_holdings"] == 0 and out["n_priced"] == 0
    assert out["holdings"] == [] and out["sectors"] == []
    assert out["freshness"] == "unavailable" and out["total_weight"] == 0.0


def test_composition_over_cap_raises_value_error(monkeypatch):
    big = {f"F{i}": Decimal("0.001") for i in range(gw_mod.COMPOSITION_MAX + 1)}
    _wire(monkeypatch, weights=big)
    with pytest.raises(ValueError):
        DbAnalyticsGateway(conn=object(), sym_conn=_SymConn([])).composition(1, now=_EPOCH)


def test_composition_writes_nothing(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn([("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD", None, None, None, None, 100.0)])
    monkeypatch.setattr(quotes, "fetch_quotes_batch",
                        lambda s, **kw: {"AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH)})
    DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    joined = " ".join(sym.seen).upper()
    assert "INSERT" not in joined and "UPDATE" not in joined and "DELETE" not in joined


def test_route_missing_portfolio_404():
    class _Gw:
        def composition(self, pid):
            raise LookupError("portfolio 999 not found")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_composition(pid=999, gw=_Gw())
    assert exc.value.status_code == 404


def test_route_over_cap_422():
    class _Gw:
        def composition(self, pid):
            raise ValueError("portfolio too large for a live composition")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_composition(pid=1, gw=_Gw())
    assert exc.value.status_code == 422


def test_route_maps_unreachable_to_503():
    class _Gw:
        def composition(self, pid):
            raise QuoteSourceUnreachable("down")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_composition(pid=1, gw=_Gw())
    assert exc.value.status_code == 503
    assert "quote provider unreachable" in exc.value.detail
