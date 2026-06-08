"""Universe registry persistence (Story U1.1).

Reads/writes the ``universe`` table. ``add_universe`` validates the kind in
Python (a clean error, ahead of the DB CHECK backstop) and is idempotent on the
universe_id; ``list_universes`` returns the registered universes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sym.universe.registry import validate_kind, validate_universe_id


@dataclass(frozen=True)
class Universe:
    universe_id: str
    name: str
    kind: str
    config: dict[str, Any]
    pit_valid_from: date | None
    source_pref: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def add_universe(
    conn: psycopg.Connection,
    universe_id: str,
    *,
    kind: str,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    pit_valid_from: date | None = None,
    source_pref: list[str] | dict[str, Any] | None = None,
) -> bool:
    """Register a universe; return True if inserted, False if it already exists.

    Validates ``universe_id`` and ``kind`` before touching the database (raises
    :class:`InvalidUniverseIdError` / :class:`UnknownUniverseKindError`), so a bad
    input is a clean typed error rather than a raw DB ``CheckViolation``. ``name``
    defaults to ``universe_id``. Idempotent: a re-add of the same id is a no-op
    (ON CONFLICT DO NOTHING).
    """
    validate_universe_id(universe_id)
    validate_kind(kind)
    row = conn.execute(
        """
        INSERT INTO universe (universe_id, name, kind, config, pit_valid_from, source_pref)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (universe_id) DO NOTHING
        RETURNING universe_id
        """,
        (
            universe_id,
            name or universe_id,
            kind,
            Jsonb(config or {}),
            pit_valid_from,
            Jsonb(source_pref) if source_pref is not None else None,
        ),
    ).fetchone()
    return row is not None


def list_universes(conn: psycopg.Connection) -> list[Universe]:
    """All registered universes, ordered by id."""
    rows = conn.execute(
        """
        SELECT universe_id, name, kind, config, pit_valid_from, source_pref,
               created_at, updated_at
          FROM universe
         ORDER BY universe_id
        """
    ).fetchall()
    return [Universe(*row) for row in rows]
