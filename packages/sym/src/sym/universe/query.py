"""As-of membership query API (Story U1.5).

Reads the ``universe_membership`` projection to answer "who was a member of this
universe on date D" — the research cross-section, joinable to ``fact_returns`` —
and composes set operations across universes. Enforces the ``pit_valid_from``
honesty boundary: a query before a universe's trustworthy-history start is
refused, never silently answered with today's members back-projected.
"""

from __future__ import annotations

from datetime import date

import psycopg

from sym.universe.registry import PitBoundaryError, UnknownUniverseError


def assert_within_pit(as_of_date: date, pit_valid_from: date | None) -> None:
    """Raise :class:`PitBoundaryError` if ``as_of_date`` precedes ``pit_valid_from``.

    ``pit_valid_from`` NULL means no known boundary (history not yet pinned) →
    allowed. This is the survivorship guardrail (no silent back-projection).
    """
    if pit_valid_from is not None and as_of_date < pit_valid_from:
        raise PitBoundaryError(
            f"as-of {as_of_date} precedes pit_valid_from {pit_valid_from}: membership before a "
            "universe's trustworthy history is not available (would be a back-projection)"
        )


def _pit_valid_from(conn: psycopg.Connection, universe_id: str) -> date | None:
    row = conn.execute(
        "SELECT pit_valid_from FROM universe WHERE universe_id = %s", (universe_id,)
    ).fetchone()
    if row is None:
        raise UnknownUniverseError(f"unknown universe {universe_id!r}")
    return row[0]


def members(conn: psycopg.Connection, universe_id: str, as_of_date: date) -> set[str]:
    """The CompositeFIGI set that was a member of ``universe_id`` on ``as_of_date``.

    Enforces the pit boundary first. The returned FIGIs join directly to
    ``fact_returns`` for the research cross-section.
    """
    assert_within_pit(as_of_date, _pit_valid_from(conn, universe_id))
    rows = conn.execute(
        """
        SELECT composite_figi
          FROM universe_membership
         WHERE universe_id = %s
           AND valid_from <= %s
           AND (valid_to IS NULL OR valid_to > %s)
        """,
        (universe_id, as_of_date, as_of_date),
    ).fetchall()
    return {r[0] for r in rows}


def members_overlap(conn: psycopg.Connection, a: str, b: str, as_of_date: date) -> set[str]:
    """FIGIs in BOTH universes as-of ``as_of_date``."""
    return members(conn, a, as_of_date) & members(conn, b, as_of_date)


def members_in_a_not_b(conn: psycopg.Connection, a: str, b: str, as_of_date: date) -> set[str]:
    """FIGIs in ``a`` but not ``b`` as-of ``as_of_date``."""
    return members(conn, a, as_of_date) - members(conn, b, as_of_date)


def members_union(conn: psycopg.Connection, a: str, b: str, as_of_date: date) -> set[str]:
    """FIGIs in EITHER universe as-of ``as_of_date``."""
    return members(conn, a, as_of_date) | members(conn, b, as_of_date)
