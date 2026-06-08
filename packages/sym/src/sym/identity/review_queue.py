"""Writes to ``securities_review_queue`` (FR-4 review surface).

The queue holds identifier inputs that did not resolve to a single clean
CompositeFIGI. It is intentionally decoupled from ``securities`` (no FK): these
rows describe inputs that have no clean security yet. A partial unique index
keeps at most one OPEN row per ``source_key``, so re-running resolution does not
re-queue an input that is still pending.
"""

from __future__ import annotations

import json

import psycopg

from sym.identity.universe import ResolutionInput


def source_key(query: ResolutionInput) -> str:
    """Canonical dedupe key for an unresolved input.

    Mirrors the examples in the migration comment: ``ticker:AAPL@XNAS`` /
    ``isin:US0378331005``.
    """
    if query.mic:
        return f"{query.symbol_type}:{query.symbol_value}@{query.mic}"
    return f"{query.symbol_type}:{query.symbol_value}"


def enqueue_review(
    conn: psycopg.Connection,
    *,
    query: ResolutionInput,
    status: str,
    candidates: list[dict] | None = None,
    detail: str | None = None,
    source_input: dict | None = None,
) -> bool:
    """Insert one OPEN review row; a no-op if an open row for the key already exists.

    Returns True if a row was inserted, False if an open duplicate suppressed it.
    """
    payload = source_input or {
        "symbol_type": query.symbol_type,
        "symbol_value": query.symbol_value,
        "mic": query.mic,
    }
    row = conn.execute(
        """
        INSERT INTO securities_review_queue
            (source_key, source_input, candidates, status, detail)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (source_key) WHERE resolved_at IS NULL DO NOTHING
        RETURNING review_id
        """,
        (
            source_key(query),
            json.dumps(payload),
            json.dumps(candidates or []),
            status,
            detail,
        ),
    ).fetchone()
    return row is not None
