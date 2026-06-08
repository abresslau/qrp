"""Tests for the universe registry + provider abstraction (Story U1.1). DB-free.

Covers the AR-5-style registry (register/get/unknown-raises + the plug-in test)
and `add_universe`'s kind validation (raises before any DB call). The table
insert/list round-trip is verified live, per the project's DB-free-unit-tests +
live-verification approach.
"""

from __future__ import annotations

from datetime import date

import pytest

from sym.universe import registry
from sym.universe.registry import (
    INDEX,
    VALID_KINDS,
    InvalidUniverseIdError,
    MembershipChange,
    UniverseProvider,
    UnknownUniverseKindError,
    get_provider,
    is_registered,
    register_provider,
    registered_kinds,
)
from sym.universe.store import add_universe


class _DummyProvider:
    """A throwaway provider proving a new provider registers without touching
    the registry's code (the plug-in test, AC #4)."""

    kind = INDEX

    def members(self, start: date, end: date):
        return [MembershipChange("AAPL", "join", start, source="dummy")]


@pytest.fixture(autouse=True)
def _isolate_registry():
    # snapshot/restore the module-level registry so tests don't leak
    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


# --- registry ---------------------------------------------------------------


def test_register_and_get_provider_roundtrips():
    register_provider(INDEX, _DummyProvider)
    assert is_registered(INDEX)
    provider = get_provider(INDEX)
    assert isinstance(provider, UniverseProvider)  # structural (runtime_checkable)
    assert provider.kind == INDEX


def test_plugin_test_new_provider_registers_without_registry_changes():
    # AC #4: a brand-new provider becomes resolvable purely by registering.
    assert not is_registered(INDEX)
    register_provider(INDEX, _DummyProvider)
    assert INDEX in registered_kinds()
    [change] = list(get_provider(INDEX).members(date(2024, 1, 2), date(2024, 1, 3)))
    assert change.raw_identifier == "AAPL" and change.change == "join"


def test_get_unregistered_kind_raises():
    with pytest.raises(UnknownUniverseKindError):
        get_provider(INDEX)  # valid kind, but nothing registered for it


def test_register_invalid_kind_raises():
    with pytest.raises(UnknownUniverseKindError):
        register_provider("bogus", _DummyProvider)


def test_valid_kinds_are_the_three():
    assert VALID_KINDS == ("custom_list", "index", "criteria")


# --- store validation (no DB) -----------------------------------------------


class _ExplodingConn:
    """Any DB call is a bug: kind validation must happen before touching the DB."""

    def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("add_universe must validate kind before any DB call")


def test_add_universe_unknown_kind_raises_before_db():
    with pytest.raises(UnknownUniverseKindError):
        add_universe(_ExplodingConn(), "validid", kind="bogus")


@pytest.mark.parametrize("bad_id", ["SP500", "", "-tmp", "my universe", "a.b"])
def test_add_universe_invalid_id_raises_before_db(bad_id):
    # AC: a bad slug is a clean typed error before the DB CHECK fires (no DB call).
    with pytest.raises(InvalidUniverseIdError):
        add_universe(_ExplodingConn(), bad_id, kind="index")
