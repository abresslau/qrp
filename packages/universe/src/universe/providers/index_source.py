"""Index source archetypes (Epic U2, FR3).

Index providers are organised **by source archetype, not one-per-index**: an
open-finance-API source (FMP), an ETF-holdings source, and a Wikipedia source.
Each archetype is an :class:`IndexSource` — it knows how to turn an *index key*
(``sp500``, ``dax`` …) and a date window into membership-change events. A single
``IndexProvider`` (Story U2.4) selects between them per-index via an ordered
source preference with automatic fallback.

This module ships the archetype contract + an archetype-keyed registry (parallel
to the kind-keyed provider registry in ``registry.py``); the concrete sources
self-register at import (``fmp``, ``etf_holdings``, ``wikipedia``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Protocol, runtime_checkable

from universe.registry import MembershipChange, UniverseError

# Archetype keys (the values used in a universe's source_pref list).
ARCHETYPE_FMP = "fmp"
ARCHETYPE_ETF = "etf_holdings"
ARCHETYPE_WIKIPEDIA = "wikipedia"
ARCHETYPE_B3 = "b3"  # official B3 (Brazil) index portfolio — authoritative, snapshot
ARCHETYPES: tuple[str, ...] = (
    ARCHETYPE_FMP,
    ARCHETYPE_ETF,
    ARCHETYPE_WIKIPEDIA,
    ARCHETYPE_B3,
)


class IndexSourceError(UniverseError):
    """A source failed to produce membership for an index.

    Raised on transport failure, an empty/garbled parse, or an unavailable
    endpoint — anything that means "this source could not answer", so the
    orchestrator falls back to the next preferred source rather than silently
    recording "no members" (NFR2: an empty parse is an error, never "no change").
    """


class UnknownArchetypeError(UniverseError):
    """A source archetype with no registered implementation."""


@runtime_checkable
class IndexSource(Protocol):
    """Turns an index key + window into membership-change events.

    A *dated* source (FMP historical, Wikipedia revision-diff) emits exact-dated
    join/leave events within the window; a *snapshot* source (ETF holdings, a
    Wikipedia current table) emits ``join`` events for the members observed at
    ``end`` with ``poll_bounded`` precision. ``fetch`` raises
    :class:`IndexSourceError` on any failure so the orchestrator can fall back.
    """

    archetype: str

    def fetch(self, index_key: str, start: date, end: date) -> list[MembershipChange]: ...


_SOURCE_REGISTRY: dict[str, Callable[..., IndexSource]] = {}


def register_index_source(archetype: str, factory: Callable[..., IndexSource]) -> None:
    """Register an :class:`IndexSource` ``factory`` under an ``archetype`` key."""
    if archetype not in ARCHETYPES:
        raise UnknownArchetypeError(
            f"{archetype!r} is not a known archetype (expected one of {ARCHETYPES})"
        )
    _SOURCE_REGISTRY[archetype] = factory


def is_registered(archetype: str) -> bool:
    return archetype in _SOURCE_REGISTRY


def get_index_source(archetype: str, **kwargs: Any) -> IndexSource:
    """Construct the source registered for ``archetype`` (raises if unknown)."""
    if archetype not in _SOURCE_REGISTRY:
        raise UnknownArchetypeError(f"no index source registered for archetype {archetype!r}")
    return _SOURCE_REGISTRY[archetype](**kwargs)
