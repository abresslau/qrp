"""Wikidata industry→GICS source tests — fake client, no network."""

from __future__ import annotations

import pytest

from sym.classification.gics import SecurityIdentity
from sym.classification.wikidata import (
    MAX_CONSECUTIVE_ERRORS,
    WikidataGicsSource,
    dominant_sector,
    industry_to_gics,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("software industry", "Information Technology"),
        ("semiconductor industry", "Information Technology"),
        ("pharmaceutical industry", "Health Care"),
        ("bank", "Financials"),
        ("investment banking", "Financials"),
        ("petroleum industry", "Energy"),
        ("mining", "Materials"),
        ("automotive industry", "Consumer Discretionary"),
        ("food industry", "Consumer Staples"),
        ("telecommunications", "Communication Services"),
        ("electric utility", "Utilities"),
        ("real estate", "Real Estate"),
        ("aerospace", "Industrials"),
        ("blockchain", None),  # uncovered → None, never guessed
        (None, None),
    ],
)
def test_industry_to_gics(label, expected):
    assert industry_to_gics(label) == expected


def test_dominant_sector_picks_the_mode():
    # Apple-like: many IT industries + one consumer-electronics → IT wins by mode
    industries = [
        "software development", "software industry", "information technology industry",
        "mobile phone industry", "consumer electronics industry",
    ]
    assert dominant_sector(industries) == "Information Technology"


def test_dominant_sector_none_when_nothing_maps():
    assert dominant_sector(["conglomerate", "holding company"]) is None


class _FakeWikidataClient:
    def __init__(self, by_isin, raises_on=None):
        self._by_isin = by_isin
        self._raises_on = raises_on or set()
        self.batches: list[list[str]] = []

    def industries_for_isins(self, isins):
        self.batches.append(list(isins))
        if any(i in self._raises_on for i in isins):
            raise RuntimeError("SPARQL 500")
        return {i: self._by_isin[i] for i in isins if i in self._by_isin}


def test_fetch_classifies_by_isin_with_provenance():
    client = _FakeWikidataClient(
        {"US0378331005": ["software industry", "consumer electronics industry"]}
    )
    src = WikidataGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_AAPL", isin="US0378331005", ticker="AAPL", mic="XNAS")])

    c = out["FIGI_AAPL"]
    assert c.sector_name == "Information Technology"
    assert c.source == "wikidata"
    assert c.industry_name is None  # sector-only


def test_fetch_records_no_isin_and_unmapped():
    client = _FakeWikidataClient({"US1111111111": ["conglomerate"]})
    src = WikidataGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_NOISIN", ticker="X"),  # no ISIN
            SecurityIdentity("FIGI_UNMAP", isin="US1111111111", ticker="Y"),
        ]
    )
    assert out == {}
    assert "FIGI_NOISIN" in src.last_unmatched
    assert src.last_unmapped == {"FIGI_UNMAP": ["conglomerate"]}


def test_fetch_circuit_breaker_short_circuits_on_batch_errors():
    # every batch errors → after K batches the breaker trips, remaining ISINs recorded
    isins = [f"X{i:010d}" for i in range((MAX_CONSECUTIVE_ERRORS + 3) * 50)]
    client = _FakeWikidataClient({}, raises_on=set(isins))
    src = WikidataGicsSource(client=client)
    out = src.fetch([SecurityIdentity(f"F{i}", isin=isins[i]) for i in range(len(isins))])

    assert out == {}
    assert len(client.batches) == MAX_CONSECUTIVE_ERRORS  # stopped after K failed batches
    assert len(src.last_short_circuited) > 0
