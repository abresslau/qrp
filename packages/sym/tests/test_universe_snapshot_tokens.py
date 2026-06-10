"""Snapshot declaration on providers (Story U3.5, Task 1). DB-free.

Each archetype source that returns a FULL current snapshot must expose it as
``last_snapshot_tokens`` after fetch — the monitor's leaver diff derives leaves
ONLY from a declared snapshot, never by inferring from event shapes (Wikipedia
emits EXACT-dated joins for current members; FMP mixes a current snapshot with
dated history — date precision says nothing about set completeness).
"""

from __future__ import annotations

from datetime import date

from sym.universe.providers.b3 import B3IndexSource
from sym.universe.providers.criteria import CriteriaProvider
from sym.universe.providers.etf_holdings import EtfHoldingsIndexSource
from sym.universe.providers.fmp import FmpIndexSource
from sym.universe.providers.index_provider import IndexProvider
from sym.universe.providers.index_source import IndexSourceError
from sym.universe.registry import JOIN, MembershipChange

D = date(2026, 6, 10)


def test_b3_declares_snapshot_tokens():
    class _Client:
        def portfolio(self, code):
            return [{"cod": "PETR4"}, {"cod": "VALE3"}]

    src = B3IndexSource(_Client())
    changes = src.fetch("ibov", D, D)
    assert src.last_snapshot_tokens == {c.raw_identifier for c in changes}
    assert src.last_snapshot_tokens == {"ticker:PETR4@BVMF", "ticker:VALE3@BVMF"}


def test_etf_declares_snapshot_tokens():
    class _Client:
        def holdings(self, etf_key):
            # normalized row keys (the HTTP client's parse_holdings_csv output shape)
            return [
                {"name": "A", "isin": "US0000000001", "asset_class": "Equity"},
                {"name": "B", "isin": "US0000000002", "asset_class": "Equity"},
            ]

    src = EtfHoldingsIndexSource(_Client(), {"dax": "exs1"})
    changes = src.fetch("dax", D, D)
    assert src.last_snapshot_tokens == {c.raw_identifier for c in changes}
    assert len(src.last_snapshot_tokens) == 2


def test_fmp_snapshot_excludes_dated_history():
    class _Client:
        def current_constituents(self, slug):
            return [{"symbol": "AAA", "exchange": "NYSE"}, {"symbol": "BBB", "exchange": "NYSE"}]

        def historical_constituents(self, slug):
            # A dated leave for a departed name — NOT part of the current snapshot.
            return [{"date": "June 1, 2026", "symbol": "", "removedTicker": "OLD",
                     "exchange": "NYSE"}]

    src = FmpIndexSource(_Client())
    changes = src.fetch("sp500", date(2026, 1, 1), D)
    assert src.last_snapshot_tokens == {"ticker:AAA@XNYS", "ticker:BBB@XNYS"}
    # the dated leave still flows as a change event
    assert any(c.raw_identifier == "ticker:OLD@XNYS" for c in changes)


def test_criteria_declares_snapshot_tokens():
    class _Conn:
        def execute(self, sql, params=None):
            class _Cur:
                def fetchall(self):
                    return [("BBG000000001",), ("BBG000000002",)]

            return _Cur()

    prov = CriteriaProvider(conn=_Conn(), rule="top_n_market_cap", n=2)
    changes = list(prov.members(D, D))
    assert prov.last_snapshot_tokens == {c.raw_identifier for c in changes}
    assert prov.last_snapshot_tokens == {"figi:BBG000000001", "figi:BBG000000002"}


def test_index_provider_propagates_winning_sources_snapshot():
    class _Snap:
        archetype = "fmp"
        last_snapshot_tokens = None

        def fetch(self, index_key, start, end):
            self.last_snapshot_tokens = {"ticker:A@XNYS"}
            return [MembershipChange("ticker:A@XNYS", JOIN, end, "fmp")]

    class _Fail:
        archetype = "etf"

        def fetch(self, index_key, start, end):
            raise IndexSourceError("down")

    prov = IndexProvider("sp500", ["etf", "fmp"], sources={"etf": _Fail(), "fmp": _Snap()})
    prov.members(date(2026, 1, 1), D)
    assert prov.last_snapshot_tokens == {"ticker:A@XNYS"}


def test_index_provider_snapshot_none_when_source_declares_none():
    class _NoSnap:
        archetype = "fmp"

        def fetch(self, index_key, start, end):
            return [MembershipChange("ticker:A@XNYS", JOIN, end, "fmp")]

    prov = IndexProvider("sp500", ["fmp"], sources={"fmp": _NoSnap()})
    prov.members(date(2026, 1, 1), D)
    assert prov.last_snapshot_tokens is None
