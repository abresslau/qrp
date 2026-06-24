"""Tests for the membership resolution bridge (Story U1.3). DB-free.

Covers token parsing, the OpenFIGI-Resolution -> MemberResolution mapping, and
`resolve_identifiers` end-to-end with a fake OpenFIGI client (reusing the
identity layer's `plan_resolutions`). The DB freeze (PK + ON CONFLICT) is
verified live.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from universe.registry import RESOLVED, UNRESOLVED, InvalidMemberIdentifierError

from sym.identity.figi import FigiRecord
from sym.identity.universe import ResolutionInput
from sym.universe.resolver import (
    _seed_from_identifier,
    resolve_identifiers,
)


class _FakeClient:
    """Returns canned FIGI records keyed by each query's idValue (order-independent)."""

    def __init__(self, by_value: dict[str, list[FigiRecord]]):
        self._by_value = by_value

    def map_identifiers(self, inputs: Sequence[ResolutionInput]) -> list[list[FigiRecord]]:
        return [list(self._by_value.get(i.symbol_value, [])) for i in inputs]


# --- token parsing ----------------------------------------------------------


def test_parse_ticker_token():
    seed = _seed_from_identifier("ticker:AAPL@XNAS")
    assert seed.ticker == "AAPL" and seed.mic == "XNAS" and seed.isin is None


def test_parse_isin_token():
    seed = _seed_from_identifier("isin:US0378331005")
    assert seed.isin == "US0378331005" and seed.ticker is None and seed.mic is None


@pytest.mark.parametrize(
    "bad", ["AAPL", "ticker:AAPL", "ticker:@XNAS", "ticker:AAPL@", "isin:", "x:y"]
)
def test_parse_malformed_token_raises(bad):
    with pytest.raises(InvalidMemberIdentifierError):
        _seed_from_identifier(bad)


# --- resolve_identifiers (reuses plan_resolutions) --------------------------


def test_resolvable_ticker_is_resolved_and_frozen_figi():
    client = _FakeClient({"AAPL": [FigiRecord("BBG000B9XRY4", "BBG001S5N8V8")]})
    out = resolve_identifiers(client, {"XNAS": "US"}, ["ticker:AAPL@XNAS"])
    mr = out["ticker:AAPL@XNAS"]
    assert mr.resolution_status == RESOLVED and mr.composite_figi == "BBG000B9XRY4"


def test_unresolvable_member_is_retained_not_dropped():
    client = _FakeClient({})  # no records for anything
    out = resolve_identifiers(client, {}, ["ticker:GONE@XNYS"])
    mr = out["ticker:GONE@XNYS"]
    assert mr.resolution_status == UNRESOLVED and mr.composite_figi is None and mr.detail


def test_ambiguous_member_is_unresolved_with_detail():
    # Two distinct composites for one ISIN -> ambiguous -> retained/flagged.
    client = _FakeClient(
        {"US0000000001": [FigiRecord("BBG000000001", "A"), FigiRecord("BBG000000002", "B")]}
    )
    out = resolve_identifiers(client, {}, ["isin:US0000000001"])
    mr = out["isin:US0000000001"]
    assert mr.resolution_status == UNRESOLVED and "ambiguous" in mr.detail
