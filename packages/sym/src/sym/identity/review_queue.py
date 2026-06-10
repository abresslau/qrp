"""The ``securities_review_queue`` — write, READ, and CLOSE (FR-4 review surface).

The queue holds identifier inputs that did not resolve to a single clean
CompositeFIGI. It is intentionally decoupled from ``securities`` (no FK): these
rows describe inputs that have no clean security yet. A partial unique index
keeps at most one OPEN row per ``source_key``, so re-running resolution does not
re-queue an input that is still pending.

The queue is a GATE, not a log (Story 1.9 / Story 1.4 AC2-AC3): resolution runs
exclude seeds whose input keys have an open row (:func:`open_review_keys` feeds
the gate in ``figi.resolve_universe``), and the steward closes rows via
:func:`resolve_review` — with a FIGI pick (assignment through ``write_security``)
or as a dismissal. Closing frees the key, so the input becomes eligible again
and a recurrence re-queues fresh.
"""

from __future__ import annotations

import json
import re

import psycopg

from sym.identity.symbology import write_security
from sym.identity.universe import ResolutionInput, SeedSecurity

_FIGI_RE = re.compile(r"^[A-Z0-9]{12}$")


class ReviewQueueError(Exception):
    """A steward action that cannot proceed (unknown row, bad FIGI, unusable input)."""


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
    """Insert one OPEN review row, or REFRESH the open row's evidence for the key.

    Returns True if a row was inserted, False if an open row existed (its
    status/candidates/detail are updated in place — the operator must see the
    LATEST classification, not the evidence from the first sighting).
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
        ON CONFLICT (source_key) WHERE resolved_at IS NULL DO UPDATE
            SET status = EXCLUDED.status,
                candidates = EXCLUDED.candidates,
                detail = EXCLUDED.detail,
                source_input = EXCLUDED.source_input
        RETURNING review_id, (xmax = 0) AS inserted
        """,
        (
            source_key(query),
            json.dumps(payload),
            json.dumps(candidates or []),
            status,
            detail,
        ),
    ).fetchone()
    return bool(row and row[1])


def open_review_keys(conn: psycopg.Connection) -> set[str]:
    """Source keys with an OPEN review row — the resolution gate's exclusion set."""
    rows = conn.execute(
        "SELECT source_key FROM securities_review_queue WHERE resolved_at IS NULL"
    ).fetchall()
    return {r[0] for r in rows}


def list_reviews(conn: psycopg.Connection, *, include_resolved: bool = False) -> list[dict]:
    """Queue items for the steward (open only by default)."""
    sql = (
        "SELECT review_id, source_key, status, jsonb_array_length(candidates), "
        "detail, created_at, resolved_at FROM securities_review_queue"
    )
    if not include_resolved:
        sql += " WHERE resolved_at IS NULL"
    sql += " ORDER BY review_id"
    cols = ["review_id", "source_key", "status", "candidate_count", "detail",
            "created_at", "resolved_at"]
    return [dict(zip(cols, row, strict=True)) for row in conn.execute(sql).fetchall()]


def resolve_review(
    conn: psycopg.Connection,
    review_id: int,
    *,
    composite_figi: str | None = None,
    share_class_figi: str | None = None,
) -> str:
    """Close an open review row; with a FIGI, assign the security first.

    Returns ``'assigned'`` or ``'dismissed'``. Assignment builds the seed from
    the queued ``source_input`` and writes through :func:`write_security` (the
    symbology SCD + collision guard live there — never hand-rolled INSERTs).
    Either way ``resolved_at`` is set, the partial unique index frees the key,
    and the input becomes eligible on the next run (Story 1.4 AC3) — a
    still-unresolvable dismissal simply re-queues fresh.
    """
    row = conn.execute(
        "SELECT source_key, source_input, resolved_at "
        "FROM securities_review_queue WHERE review_id = %s",
        (review_id,),
    ).fetchone()
    if row is None:
        raise ReviewQueueError(f"no review row {review_id}")
    source_key_, source_input, resolved_at = row
    if resolved_at is not None:
        raise ReviewQueueError(f"review {review_id} ({source_key_}) already resolved")
    outcome = "dismissed"
    if composite_figi is not None:
        if not _FIGI_RE.match(composite_figi):
            raise ReviewQueueError(
                f"invalid FIGI {composite_figi!r}: expected 12 chars [A-Z0-9]"
            )
        if isinstance(source_input, str):
            source_input = json.loads(source_input)
        if source_input.get("symbol_type") != "ticker" or not source_input.get("mic"):
            raise ReviewQueueError(
                f"review {review_id} ({source_key_}) lacks a ticker+MIC input — "
                "assignment needs the listing (resolve via the seed file instead)"
            )
        seed = SeedSecurity(
            name=source_input.get("name") or source_key_,
            category=source_input.get("category") or "review_resolution",
            ticker=source_input["symbol_value"],
            mic=source_input["mic"],
            isin=None,
            note=f"steward-assigned from review {review_id}",
        )
        write_security(
            conn, seed=seed, composite_figi=composite_figi,
            share_class_figi=share_class_figi,
        )
        outcome = "assigned"
    conn.execute(
        "UPDATE securities_review_queue SET resolved_at = now() WHERE review_id = %s",
        (review_id,),
    )
    return outcome
