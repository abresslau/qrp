"""Instrument-identity helpers, operating on an injected sym connection.

Index facts are keyed on the universal ``sym_id``, which lives in the sym DB (``instrument`` /
``instrument_xref`` — the generic identity spine). The index loaders resolve and, for a new index,
CREATE that identity. These helpers are the SQL to do so; they take the sym connection as their
first argument and never touch the indices DB. They mirror ``sym.identity.instrument`` (the
canonical generic identity logic) verbatim — duplicated here, not imported, so the ``indices``
package
stays sym-import-free (the one-way topology rule) without a circular package dependency. Identity is
sym-OWNED data; these functions only read/write it over the injected connection.
"""

from __future__ import annotations

import psycopg

INDEX = "index"
SRC_YAHOO = "yahoo"
SRC_MSCI = "msci"
SRC_FIGI = "figi"


class XrefConflictError(Exception):
    """An external (source, value) already maps to a different instrument — needs an operator."""


def sym_id_for(conn: psycopg.Connection, source: str, value: str) -> int | None:
    """The sym_id an external (source, value) identifier resolves to, or None (reads the sym DB)."""
    row = conn.execute(
        "SELECT sym_id FROM instrument_xref WHERE source = %s AND value = %s", (source, value)
    ).fetchone()
    return row[0] if row else None


def xref_for(conn: psycopg.Connection, sym_id: int, source: str) -> str | None:
    """The external id of ``source`` attached to ``sym_id`` (or None)."""
    row = conn.execute(
        "SELECT value FROM instrument_xref WHERE sym_id = %s AND source = %s", (sym_id, source)
    ).fetchone()
    return row[0] if row else None


def add_xref(conn: psycopg.Connection, sym_id: int, source: str, value: str) -> None:
    """Attach an external id to an instrument (idempotent for the SAME instrument).

    Raises :class:`XrefConflictError` when the (source, value) already maps to a different sym_id —
    an identity collision needs an operator, not a no-op.
    """
    existing = sym_id_for(conn, source, value)
    if existing is not None:
        if existing != sym_id:
            raise XrefConflictError(
                f"xref ({source}, {value}) already maps to sym_id {existing}, "
                f"refusing to attach to {sym_id}"
            )
        return
    conn.execute(
        "INSERT INTO instrument_xref (sym_id, source, value) VALUES (%s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (sym_id, source, value),
    )


def ensure_instrument(
    conn: psycopg.Connection,
    kind: str,
    *,
    name: str | None = None,
    currency_code: str | None = None,
    status: str = "active",
    xrefs: dict[str, str] | None = None,
) -> int:
    """Find-or-create an instrument by its external ids; return its sym_id (operates on the sym DB).

    If any supplied xref already maps to an instrument, that sym_id is returned (and any new xrefs
    are attached) — so identity is stable and idempotent. Otherwise a new instrument is created with
    the xrefs, atomically. Raises ``ValueError`` with no xrefs, and :class:`XrefConflictError` when
    the supplied xrefs resolve to TWO different existing instruments or a kind mismatch.
    """
    xrefs = xrefs or {}
    if not xrefs:
        raise ValueError("ensure_instrument requires at least one xref (identity anchor)")
    resolved = {
        (source, value): sym_id_for(conn, source, value) for source, value in xrefs.items()
    }
    hits = {s for s in resolved.values() if s is not None}
    if len(hits) > 1:
        raise XrefConflictError(
            f"xrefs resolve to multiple instruments {sorted(hits)}: {xrefs!r} — manual merge"
        )
    if hits:
        existing = hits.pop()
        existing_kind = conn.execute(
            "SELECT kind FROM instrument WHERE sym_id = %s", (existing,)
        ).fetchone()[0]
        if existing_kind != kind:
            raise XrefConflictError(
                f"xrefs {xrefs!r} resolve to sym_id {existing} of kind "
                f"{existing_kind!r}, not {kind!r} — manual reconciliation"
            )
        for s, v in xrefs.items():
            add_xref(conn, existing, s, v)
        return existing
    with conn.transaction():
        row = conn.execute(
            """
            INSERT INTO instrument (kind, name, currency_code, status)
            VALUES (%s, %s, %s, %s) RETURNING sym_id
            """,
            (kind, name, currency_code, status),
        ).fetchone()
        sym_id = row[0]
        for source, value in xrefs.items():
            add_xref(conn, sym_id, source, value)
    return sym_id
