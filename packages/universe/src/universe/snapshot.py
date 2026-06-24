"""Reproducible universe snapshots (Story U1.6; resolution watermark U1.7).

A *snapshot pin* is ``(universe_id, as_of_date, log_version, resolved_through)``:

* ``log_version`` — a monotonic ``membership_event.event_id`` watermark; the
  pinned query re-projects from only the events ``<= log_version`` (it does NOT
  read the materialized ``universe_membership``), so later-appended events —
  including corrections — are ignored;
* ``resolved_through`` — a timestamp watermark over
  ``universe_member_resolution.resolved_at``; resolutions written (or upgraded
  from ``unresolved`` — the upgrade re-stamps ``resolved_at``) AFTER the pin are
  ignored, so a member unresolved at pin time stays out of the pin forever.

Capture both with :func:`current_log_version` + :func:`current_resolution_version`
at pin time. Determinism then follows from the projection being a pure function
of the watermarked event/resolution subsets: resolutions mutate at most once
(the upgrade-only upsert, U1.3) — if a re-pointing write path is ever added,
pin reproducibility needs resolution SCD, not just this watermark.
``resolved_through=None`` preserves the U1.6 events-only behavior (an old pin
without a stored resolution watermark remains readable, with the original,
weaker guarantee).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

import psycopg

from universe.projection import (
    MembershipEvent,
    _membership_events,
    project_membership,
)
from universe.query import _pit_valid_from, assert_within_pit
from universe.registry import UnknownUniverseError


def _assert_universe_exists(conn: psycopg.Connection, universe_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM universe WHERE universe_id = %s", (universe_id,)
    ).fetchone()
    if row is None:
        # A typo'd universe would otherwise capture a silent epoch watermark —
        # a plausible-looking pin for a universe that doesn't exist.
        raise UnknownUniverseError(f"unknown universe {universe_id!r}")


def current_log_version(conn: psycopg.Connection, universe_id: str) -> int:
    """The current log-version watermark — ``max(event_id)`` for the universe (0 if none)."""
    row = conn.execute(
        "SELECT coalesce(max(event_id), 0) FROM membership_event WHERE universe_id = %s",
        (universe_id,),
    ).fetchone()
    return row[0] if row else 0


def current_resolution_version(conn: psycopg.Connection, universe_id: str) -> datetime:
    """The current resolution watermark — ``max(resolved_at)`` (epoch if none).

    Prefer :func:`capture_pin`, which takes BOTH watermarks in one statement.
    A universe with no resolutions yet captures the epoch — a deliberately
    reproducible pin that excludes every future resolution (it pins "nothing
    was resolved"), not an error.
    """
    _assert_universe_exists(conn, universe_id)
    row = conn.execute(
        "SELECT coalesce(max(resolved_at), 'epoch'::timestamptz) "
        "FROM universe_member_resolution WHERE universe_id = %s",
        (universe_id,),
    ).fetchone()
    return row[0]


def capture_pin(conn: psycopg.Connection, universe_id: str) -> tuple[int, datetime]:
    """Capture ``(log_version, resolved_through)`` for a new pin — atomically.

    A single statement reads both watermarks from ONE snapshot, so a concurrent
    event append + resolution write can't land between two separate captures and
    produce an internally inconsistent pin.

    Capture discipline (the watermark's stated preconditions, not enforced
    guarantees): take the pin OUTSIDE an in-flight resolution run —
    ``resolved_at`` is stamped with ``now()`` (transaction-START time), so a
    resolution transaction that began before the capture but commits after it
    carries a pre-capture stamp and would join a later re-run of the pin. The
    equal-timestamp boundary (``<=``) likewise includes any row stamped exactly
    at the watermark, and the scheme assumes a monotonic database clock. For a
    single-operator pipeline these are operating rules; if pins become
    load-bearing for backtests, the robust fix is a sequence-based resolution
    watermark (see the deferred-work ledger).
    """
    _assert_universe_exists(conn, universe_id)
    row = conn.execute(
        """
        SELECT (SELECT coalesce(max(event_id), 0)
                  FROM membership_event WHERE universe_id = %s),
               (SELECT coalesce(max(resolved_at), 'epoch'::timestamptz)
                  FROM universe_member_resolution WHERE universe_id = %s)
        """,
        (universe_id, universe_id),
    ).fetchone()
    return row[0], row[1]


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
    conn: psycopg.Connection,
    universe_id: str,
    as_of_date: date,
    log_version: int,
    *,
    resolved_through: datetime | None = None,
) -> set[str]:
    """Members as-of ``as_of_date`` as the log AND resolutions stood at the pin.

    Enforces the pit boundary, then re-projects from events ``<= log_version``
    joined to resolutions with ``resolved_at <= resolved_through`` — the same
    pin always returns the same set, including across later resolution upgrades
    (U1.7). ``resolved_through=None`` is the legacy U1.6 events-only pin: still
    deterministic over events, but a post-pin resolution upgrade changes it.

    One-time semantic shift (U3.7): re-projection now routes correctives through
    tombstone pairing, so a pre-U3.7 pin whose window contains a
    reverses-corrective can differ from what it returned under toggle semantics.
    Forward reproducibility is unaffected — a watermark can never include a
    corrective without its target (``reverse_change`` validates the target
    exists before appending, and ``event_id`` is monotonic).
    """
    assert_within_pit(as_of_date, _pit_valid_from(conn, universe_id))
    events = _membership_events(
        conn, universe_id, through=log_version, resolved_through=resolved_through
    )
    return members_from_events(events, as_of_date)
