"""Universal internal instrument identity — `sym_id` (Benchmark epic, B1).

`sym_id` is a stable internal surrogate spanning every instrument kind (equity,
index, …). External vendor identifiers (CompositeFIGI, Yahoo symbol, MSCI code,
ISIN, FIGI) live in ``instrument_xref``, so identity never depends on any one
vendor. This is **additive**: the existing composite_figi-keyed equity tables are
untouched; each security is mapped 1:1 to an instrument via a ``composite_figi``
xref (``backfill_equity_instruments``), and new kinds (indexes) use ``sym_id``
natively.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

# Instrument kinds (matches instrument_kind_chk).
EQUITY = "equity"
INDEX = "index"

# External-id sources (instrument_xref.source). Open-ended; these are the known ones.
SRC_COMPOSITE_FIGI = "composite_figi"
SRC_YAHOO = "yahoo"
SRC_MSCI = "msci"
SRC_ISIN = "isin"
SRC_FIGI = "figi"


def sym_id_for(conn: psycopg.Connection, source: str, value: str) -> int | None:
    """The sym_id an external (source, value) identifier resolves to, or None."""
    row = conn.execute(
        "SELECT sym_id FROM instrument_xref WHERE source = %s AND value = %s", (source, value)
    ).fetchone()
    return row[0] if row else None


def xref_for(conn: psycopg.Connection, sym_id: int, source: str) -> str | None:
    """One external id of a given source for an instrument (None if absent)."""
    row = conn.execute(
        "SELECT value FROM instrument_xref WHERE sym_id = %s AND source = %s LIMIT 1",
        (sym_id, source),
    ).fetchone()
    return row[0] if row else None


def add_xref(conn: psycopg.Connection, sym_id: int, source: str, value: str) -> None:
    """Attach an external id to an instrument (idempotent; UNIQUE(source,value) guards)."""
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
    """Find-or-create an instrument by its external ids; return its sym_id.

    If any supplied xref already maps to an instrument, that sym_id is returned
    (and any new xrefs are attached) — so identity is stable and idempotent.
    Otherwise a new instrument is created with all the xrefs.
    """
    xrefs = xrefs or {}
    for source, value in xrefs.items():
        existing = sym_id_for(conn, source, value)
        if existing is not None:
            for s, v in xrefs.items():
                add_xref(conn, existing, s, v)
            return existing
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


@dataclass
class BackfillSummary:
    created: int = 0
    existed: int = 0


def backfill_equity_instruments(conn: psycopg.Connection) -> BackfillSummary:
    """Map every `securities` row to an `instrument(kind='equity')` (additive, idempotent).

    Creates one instrument per security not yet mapped, with the current company
    name + the security's currency/status, and a ``composite_figi`` xref. Existing
    mappings are left untouched.
    """
    conn.autocommit = True
    rows = conn.execute(
        """
        SELECT s.composite_figi, s.currency_code, s.status,
               (SELECT n.name FROM security_names n
                 WHERE n.composite_figi = s.composite_figi AND n.valid_to IS NULL) AS name
          FROM securities s
         WHERE NOT EXISTS (
             SELECT 1 FROM instrument_xref x
              WHERE x.source = %s AND x.value = s.composite_figi
         )
         ORDER BY s.composite_figi
        """,
        (SRC_COMPOSITE_FIGI,),
    ).fetchall()
    summary = BackfillSummary()
    for figi, currency, status, name in rows:
        ensure_instrument(
            conn, EQUITY, name=name, currency_code=currency, status=status,
            xrefs={SRC_COMPOSITE_FIGI: figi},
        )
        summary.created += 1
    summary.existed = conn.execute(
        "SELECT count(*) FROM instrument WHERE kind = %s", (EQUITY,)
    ).fetchone()[0] - summary.created
    return summary
