"""Live quote source (Story QH.2). DB-free — fake conn + monkeypatched HTTP fetch.

Covers symbol mapping, payload parse, freshness thresholds, live return, the gateway's
per-symbol-unavailable vs whole-source-503 split, and the route's bounds + 503 mapping.
"""

from __future__ import annotations

import urllib.error

import pytest
from fastapi import HTTPException

from qrp_api.modules.sym import quotes
from qrp_api.modules.sym import router as router_mod
from qrp_api.modules.sym.gateway import DbSymGateway
from qrp_api.modules.sym.quotes import QuoteSourceUnreachable, RawQuote

# A captured-shape Yahoo v8 chart payload (trimmed to what the parser reads).
_PAYLOAD = """
{"chart":{"result":[{"meta":{"regularMarketPrice":296.42,"previousClose":291.13,
"chartPreviousClose":291.13,"regularMarketTime":1781553601,"currency":"USD"}}]}}
"""


# --- symbol mapping ---------------------------------------------------------------

def test_yahoo_symbol_for_maps_suffix_and_share_class():
    assert quotes.yahoo_symbol_for("AAPL", "XNAS") == "AAPL"      # US: no suffix
    assert quotes.yahoo_symbol_for("PETR4", "BVMF") == "PETR4.SA"  # B3
    assert quotes.yahoo_symbol_for("HSBA", "XLON") == "HSBA.L"     # LSE
    assert quotes.yahoo_symbol_for("BRK.A", "XNYS") == "BRK-A"     # share class '.'->'-'


def test_yahoo_symbol_for_unmapped_or_missing_is_none():
    assert quotes.yahoo_symbol_for("FOO", "XZZZ") is None  # unknown MIC
    assert quotes.yahoo_symbol_for(None, "XNAS") is None   # no ticker


# --- payload parse ----------------------------------------------------------------

def test_fetch_raw_quote_parses_meta(monkeypatch):
    monkeypatch.setattr(quotes, "_http_get", lambda url, timeout: _PAYLOAD)
    q = quotes.fetch_raw_quote("AAPL")
    assert q == RawQuote(price=296.42, prev_close=291.13, currency="USD", quote_epoch=1781553601)


def test_fetch_raw_quote_no_price_is_none(monkeypatch):
    monkeypatch.setattr(quotes, "_http_get", lambda url, timeout: '{"chart":{"result":[{"meta":{}}]}}')
    assert quotes.fetch_raw_quote("AAPL") is None


def test_fetch_raw_quote_http_error_is_unavailable_not_outage(monkeypatch):
    def _boom(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(quotes, "_http_get", _boom)
    assert quotes.fetch_raw_quote("NOPE") is None  # per-symbol miss, not a source outage


def test_fetch_raw_quote_network_error_raises_unreachable(monkeypatch):
    def _boom(url, timeout):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(quotes, "_http_get", _boom)
    with pytest.raises(QuoteSourceUnreachable):
        quotes.fetch_raw_quote("AAPL")


def test_fetch_raw_quote_malformed_numeric_is_unavailable_not_500(monkeypatch):
    # A non-numeric price/time must degrade to a per-symbol miss (None), never raise into a 500.
    bad = ('{"chart":{"result":[{"meta":{"regularMarketPrice":"n/a",'
           '"previousClose":291.13,"regularMarketTime":"soon","currency":"USD"}}]}}')
    monkeypatch.setattr(quotes, "_http_get", lambda url, timeout: bad)
    assert quotes.fetch_raw_quote("AAPL") is None


# --- freshness + return -----------------------------------------------------------

def test_classify_freshness_live_vs_delayed():
    assert quotes.classify_freshness(1000, 1050) == ("live", 50)
    assert quotes.classify_freshness(1000, 1000 + 600) == ("delayed", 600)
    assert quotes.classify_freshness(None, 1000) == ("delayed", None)


def test_live_return_ratio_and_null_rule():
    assert quotes.live_return(110.0, 100.0) == pytest.approx(0.10)
    assert quotes.live_return(100.0, 0.0) is None
    assert quotes.live_return(None, 100.0) is None


# --- gateway assembly -------------------------------------------------------------

class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return _Cur(self._rows)


def test_quotes_assembles_rows_with_unavailable_for_unmapped(monkeypatch):
    # FIGI2 has an unmapped MIC -> unavailable; FIGI1 resolves + fetches.
    conn = _Conn([("FIGI1", "AAPL", "XNAS"), ("FIGI2", "XYZ", "XZZZ")])
    monkeypatch.setattr(
        quotes, "fetch_raw_quote",
        lambda sym, **kw: RawQuote(296.42, 291.13, "USD", 1781553601),
    )
    out = DbSymGateway(conn).quotes(["FIGI1", "FIGI2"], now=1781553601 + 30)
    by = {r["figi"]: r for r in out}
    assert by["FIGI1"]["freshness"] == "live"
    assert by["FIGI1"]["yahoo_symbol"] == "AAPL"
    assert by["FIGI1"]["live_return"] == pytest.approx(296.42 / 291.13 - 1)
    assert by["FIGI2"]["freshness"] == "unavailable" and by["FIGI2"]["price"] is None


def test_quotes_per_symbol_miss_is_not_a_request_failure(monkeypatch):
    conn = _Conn([("FIGI1", "AAPL", "XNAS")])
    monkeypatch.setattr(quotes, "fetch_raw_quote", lambda sym, **kw: None)  # reachable, no data
    out = DbSymGateway(conn).quotes(["FIGI1"], now=1781553601)
    assert out[0]["freshness"] == "unavailable" and out[0]["price"] is None


def test_quotes_all_network_errors_raise_unreachable(monkeypatch):
    conn = _Conn([("FIGI1", "AAPL", "XNAS"), ("FIGI2", "MSFT", "XNAS")])

    def _boom(sym, **kw):
        raise QuoteSourceUnreachable("down")

    monkeypatch.setattr(quotes, "fetch_raw_quote", _boom)
    with pytest.raises(QuoteSourceUnreachable):
        DbSymGateway(conn).quotes(["FIGI1", "FIGI2"], now=1781553601)


def test_quotes_writes_nothing():
    # The fetch path issues exactly one SELECT (ticker/mic) and never an INSERT/UPDATE/DELETE.
    seen = []

    class _SpyConn(_Conn):
        def execute(self, sql, params=None):
            seen.append(sql)
            return _Cur([])

    DbSymGateway(_SpyConn([])).quotes([], now=1.0)
    assert all("INSERT" not in s.upper() and "UPDATE" not in s.upper()
               and "DELETE" not in s.upper() for s in seen)


# --- route bounds + 503 mapping ---------------------------------------------------

class _Gw:
    def __init__(self, fn):
        self._fn = fn

    def quotes(self, ids):
        return self._fn(ids)


def test_route_rejects_empty_and_oversized():
    with pytest.raises(HTTPException) as e1:
        router_mod.quotes(figis="", gw=_Gw(lambda ids: []))
    assert e1.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        router_mod.quotes(figis=",".join(f"F{i}" for i in range(51)), gw=_Gw(lambda ids: []))
    assert e2.value.status_code == 422


def test_route_maps_unreachable_to_503():
    def _boom(ids):
        raise QuoteSourceUnreachable("down")
    with pytest.raises(HTTPException) as exc:
        router_mod.quotes(figis="FIGI1", gw=_Gw(_boom))
    assert exc.value.status_code == 503
    assert "quote provider unreachable" in exc.value.detail
