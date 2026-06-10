"""Reproducible universe snapshots (Story U1.6).

A *snapshot pin* is ``(universe_id, as_of_date, log_version)`` where ``log_version`` is
a monotonic ``membership_event.event_id`` watermark. A pinned membership query
re-projects from only the events ``<= log_version`` (it does NOT read the
materialized ``universe_membership``, which reflects the latest rebuild), so
later-appended events — including corrections — are ignored and a re-run of the
same pin yields identical membership. Determinism follows from the projection
being a pure function of the ordered event subset (resolutions are frozen, U1.3).

KNOWN CAVEAT (deferred): the pin watermarks EVENTS, not resolutions. A member
that resolves (or upgrades from `unresolved`) AFTER the pin was taken changes a
later re-run of the same pin — full reproducibility needs a resolution watermark
(e.g. resolved_at <= pin time), which the schema does not carry yet. See the
deferred-work ledger (chunk-3 review, D2).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import psycopg

from sym.universe.projection import (
    MembershipEvent,
    _membership_events,
    project_membership,
)
from sym.universe.query import _pit_valid_from, assert_within_pit


def current_log_version(conn: psycopg.Connection, universe_id: str) -> int:
    """The current log-version watermark — ``max(event_id)`` for the universe (0 if none)."""
    row = conn.execute(
        "SELECT coalesce(max(event_id), 0) FROM membership_event WHERE universe_id = %s",
        (universe_id,),
    ).fetchone()
    return row[0] if row else 0


def members_from_events(events: Iterable[MembershipEvent], as_of_date: date) -> set[str]:
    """The CompositeFIGI set that was a member on ``as_of_date`` given ``events`` (pure).

    Projects the events to intervals and selects FIGIs whose interval covers
    ``as_of_date`` (half-open ``[valid_from, valid_to)``).
    """
    members: set[str] = set()
    for figi, intervals in project_membership(events).items():
        for iv in intervals:
            if iv.valid_from <= as_of_date and (iv.valid_to is None or iv.valid_to > as_of_date):
                members.add(figi)
                break
    return members


def members_pinned(
    conn: psycopg.Connection, universe_id: str, as_of_date: date, log_version: int
) -> set[str]:
    """Members as-of ``as_of_date`` as the log stood at ``log_version`` (reproducible).

    Enforces the pit boundary, then re-projects from events ``<= log_version`` so
    later-appended events are ignored — the same pin always returns the same set.
    """
    assert_within_pit(as_of_date, _pit_valid_from(conn, universe_id))
    events = _membership_events(conn, universe_id, through=log_version)
    return members_from_events(events, as_of_date)
