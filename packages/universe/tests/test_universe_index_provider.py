"""Tests for the index provider's source preference + fallback (Story U2.4). DB-free."""

from __future__ import annotations

from datetime import date

import pytest

from universe.providers.index_provider import IndexProvider
from universe.providers.index_source import IndexSourceError
from universe.registry import INDEX, JOIN, MembershipChange, get_provider, is_registered


class _FakeSource:
    def __init__(self, archetype, changes=None, fail=False):
        self.archetype = archetype
        self._changes = changes or []
        self._fail = fail
        self.calls = 0

    def fetch(self, index_key, start, end):
        self.calls += 1
        if self._fail:
            raise IndexSourceError(f"{self.archetype} boom")
        return self._changes


def _chg(tok):
    return MembershipChange(tok, JOIN, date(2024, 1, 1), "x")


def test_index_provider_is_registered():
    import universe.providers  # noqa: F401

    assert is_registered(INDEX)


def test_requires_index_key():
    with pytest.raises(IndexSourceError):
        IndexProvider(index=None)


def test_uses_preferred_source_first():
    fmp = _FakeSource("fmp", [_chg("ticker:A@XNYS")])
    wiki = _FakeSource("wikipedia", [_chg("ticker:Z@XNYS")])
    prov = IndexProvider("sp500", ["fmp", "wikipedia"], sources={"fmp": fmp, "wikipedia": wiki})
    changes = prov.members(date(2000, 1, 1), date(2024, 6, 1))
    assert [c.raw_identifier for c in changes] == ["ticker:A@XNYS"]
    assert fmp.calls == 1 and wiki.calls == 0  # preferred won, no fallback


def test_falls_back_on_failure():
    fmp = _FakeSource("fmp", fail=True)
    wiki = _FakeSource("wikipedia", [_chg("ticker:Z@XNYS")])
    prov = IndexProvider("sp500", ["fmp", "wikipedia"], sources={"fmp": fmp, "wikipedia": wiki})
    changes = prov.members(date(2000, 1, 1), date(2024, 6, 1))
    assert [c.raw_identifier for c in changes] == ["ticker:Z@XNYS"]
    assert fmp.calls == 1 and wiki.calls == 1  # fell back


def test_empty_result_falls_through():
    fmp = _FakeSource("fmp", [])  # succeeds but produces nothing
    wiki = _FakeSource("wikipedia", [_chg("ticker:Z@XNYS")])
    prov = IndexProvider("sp500", ["fmp", "wikipedia"], sources={"fmp": fmp, "wikipedia": wiki})
    changes = prov.members(date(2000, 1, 1), date(2024, 6, 1))
    assert [c.raw_identifier for c in changes] == ["ticker:Z@XNYS"]


def test_all_sources_fail_raises_loudly():
    fmp = _FakeSource("fmp", fail=True)
    wiki = _FakeSource("wikipedia", fail=True)
    prov = IndexProvider("sp500", ["fmp", "wikipedia"], sources={"fmp": fmp, "wikipedia": wiki})
    with pytest.raises(IndexSourceError) as exc:
        prov.members(date(2000, 1, 1), date(2024, 6, 1))
    assert "all sources failed" in str(exc.value)


def test_get_provider_builds_index_provider_from_config():
    prov = get_provider(INDEX, index="sp500", source_pref=["wikipedia"])
    assert isinstance(prov, IndexProvider)
