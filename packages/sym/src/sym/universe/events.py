"""Append-only membership event log (Story U1.2, AR-6/AR-10).

The event log is the *truth* for universe membership; the interval projection
(Story U1.4) is derived from it. This module only **appends** — there is no
update or delete path, by design. Appends are idempotent on the dedupe key
``(universe_id, raw_identifier, change, effective_date)`` (a re-report of the
same change is a no-op); two sources reporting the same change at *different*
effective dates are distinct rows and both are kept (precedence is resolved at
projection time, U1.4).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sym.universe.registry import MembershipChange, validate_change, validate_precision


def append_change(
    conn: psycopg.Connection,
    universe_id: str,
    change: MembershipChange,
    *,
    provenance: dict[str, Any] | None = None,
) -> bool:
    """Append one membership change; return True if inserted, False if a duplicate.

    Validates the change kind + precision before the DB (typed
    :class:`InvalidMembershipEventError`). Idempotent via ON CONFLICT DO NOTHING
    on the dedupe key.
    """
    validate_change(change.change)
    validate_precision(change.effective_date_precision)
    row = conn.execute(
        """
        INSERT INTO membership_event
            (universe_id, raw_identifier, change, effective_date,
             effective_date_precision, source, provenance)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (universe_id, raw_identifier, change, effective_date) DO NOTHING
        RETURNING event_id
        """,
        (
            universe_id,
            change.raw_identifier,
            change.change,
            change.effective_date,
            change.effective_date_precision,
            change.source,
            Jsonb(provenance) if provenance is not None else None,
        ),
    ).fetchone()
    return row is not None


def append_changes(
    conn: psycopg.Connection,
    universe_id: str,
    changes: Iterable[MembershipChange],
    *,
    provenance: dict[str, Any] | None = None,
) -> int:
    """Append many changes; return the count actually inserted (duplicates skipped)."""
    return sum(
        append_change(conn, universe_id, change, provenance=provenance) for change in changes
    )
