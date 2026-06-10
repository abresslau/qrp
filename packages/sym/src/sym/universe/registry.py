"""Config-keyed universe-provider registry (Story U1.1, AR-5 pattern).

A universe is defined by its *kind* (``custom_list | index | criteria``), and the
concrete provider for a kind is selected from a registry — never by importing a
specific class — so a new provider plugs in by registering, with no change to the
store, resolver, or ingestion. This mirrors ``src/sym/sources/registry.py``.

Concrete providers (the custom-list provider in U1.7, index providers in U2, the
criteria provider in U5) self-register at import. U1.1 ships the abstraction and
the registry; the membership-event shape firms up in U1.2.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

# The universe kinds (matches the universe_kind_chk CHECK constraint).
CUSTOM_LIST = "custom_list"
INDEX = "index"
CRITERIA = "criteria"
VALID_KINDS: tuple[str, ...] = (CUSTOM_LIST, INDEX, CRITERIA)

# Universe-id slug rule — mirrors the universe_id_format_chk CHECK so a bad id is
# rejected cleanly in Python before the DB raises a CheckViolation.
UNIVERSE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")  # \Z: `$` would pass 'abc\n'

# A change's effective date is exact when a dated source reports it, or only
# bounded by the polling interval when derived from diffing snapshots (U1.2/U2).
EXACT = "exact"
POLL_BOUNDED = "poll_bounded"
PRECISIONS: tuple[str, ...] = (EXACT, POLL_BOUNDED)

# Membership change kinds (matches membership_event_change_chk). Providers emit
# join/leave; correct is a corrective event appended by maintenance/review (U3).
JOIN = "join"
LEAVE = "leave"
CORRECT = "correct"
CHANGE_KINDS: tuple[str, ...] = (JOIN, LEAVE, CORRECT)

# Member resolution statuses (matches universe_member_resolution_status_chk).
# unpriced is set by ingestion (U4) when a member resolves but has no prices yet.
RESOLVED = "resolved"
UNRESOLVED = "unresolved"
UNPRICED = "unpriced"
RESOLUTION_STATUSES: tuple[str, ...] = (RESOLVED, UNRESOLVED, UNPRICED)


class UniverseError(Exception):
    """Base error for the universe layer."""


class UnknownUniverseKindError(UniverseError):
    """A universe kind with no registered provider (or not a valid kind)."""


class InvalidUniverseIdError(UniverseError):
    """A universe id that violates the slug rule (universe_id_format_chk)."""


class InvalidMembershipEventError(UniverseError):
    """A membership event with an invalid change kind or effective-date precision."""


class InvalidMemberIdentifierError(UniverseError):
    """A member raw_identifier that isn't a parseable resolution token."""


class UnknownUniverseError(UniverseError):
    """A reference to a universe_id that isn't registered."""


class PitBoundaryError(UniverseError):
    """An as-of membership query before a universe's trustworthy-history boundary."""


def validate_kind(kind: str) -> None:
    """Raise :class:`UnknownUniverseKindError` if ``kind`` is not a valid kind."""
    if kind not in VALID_KINDS:
        raise UnknownUniverseKindError(
            f"{kind!r} is not a valid universe kind (expected one of {VALID_KINDS})"
        )


def validate_universe_id(universe_id: str) -> None:
    """Raise :class:`InvalidUniverseIdError` if ``universe_id`` is not a valid slug.

    Mirrors the DB ``universe_id_format_chk`` so callers get a clean, typed error
    instead of a raw ``CheckViolation`` from the INSERT.
    """
    if not UNIVERSE_ID_PATTERN.match(universe_id):
        raise InvalidUniverseIdError(
            f"{universe_id!r} is not a valid universe id "
            "(lowercase alphanumerics, '_' or '-', not leading)"
        )


def validate_change(change: str) -> None:
    """Raise :class:`InvalidMembershipEventError` if ``change`` is not a valid kind."""
    if change not in CHANGE_KINDS:
        raise InvalidMembershipEventError(
            f"{change!r} is not a valid membership change (expected one of {CHANGE_KINDS})"
        )


def validate_precision(precision: str) -> None:
    """Raise :class:`InvalidMembershipEventError` if ``precision`` is not valid."""
    if precision not in PRECISIONS:
        raise InvalidMembershipEventError(
            f"{precision!r} is not a valid effective_date_precision "
            f"(expected one of {PRECISIONS})"
        )


@dataclass(frozen=True)
class MembershipChange:
    """A single membership-change a provider emits (the provider output contract).

    ``change`` is ``join`` or ``leave``; ``effective_date_precision`` records
    whether the date is ``exact`` (dated source) or ``poll_bounded`` (snapshot
    diff). The event log (Story U1.2) persists these.
    """

    raw_identifier: str
    change: str  # join | leave
    effective_date: date
    source: str
    effective_date_precision: str = EXACT


@runtime_checkable
class UniverseProvider(Protocol):
    """Yields the membership changes that define a universe over a window.

    Event-producing providers (index, custom list) enumerate join/leave changes;
    a function-evaluating provider (criteria) computes membership and emits it as
    changes too. ``kind`` ties the provider to a registry key.
    """

    kind: str

    def members(self, start: date, end: date) -> Iterable[MembershipChange]: ...


_REGISTRY: dict[str, Callable[..., UniverseProvider]] = {}


def register_provider(kind: str, factory: Callable[..., UniverseProvider]) -> None:
    """Register a provider ``factory`` under a universe ``kind``.

    Raises :class:`UnknownUniverseKindError` if ``kind`` is not a valid universe
    kind (the registry never holds a kind the schema would reject).
    """
    validate_kind(kind)
    _REGISTRY[kind] = factory


def is_registered(kind: str) -> bool:
    return kind in _REGISTRY


def registered_kinds() -> Sequence[str]:
    return tuple(_REGISTRY)


def get_provider(kind: str, **kwargs: Any) -> UniverseProvider:
    """Construct the provider registered for ``kind``.

    Raises :class:`UnknownUniverseKindError` for a kind with no registered
    provider (whether invalid or simply not yet implemented).
    """
    if kind not in _REGISTRY:
        raise UnknownUniverseKindError(f"no universe provider registered for kind {kind!r}")
    return _REGISTRY[kind](**kwargs)
