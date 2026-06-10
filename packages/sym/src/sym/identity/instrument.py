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


class XrefConflictError(Exception):
    """An external (source, value) id is already claimed by a DIFFERENT instrument.

    On an identity spine this is the one event that must be loud — silently keeping
    the old mapping (ON CONFLICT DO NOTHING) would leave two instruments believing
    they own one vendor id, with no breadcrumb.
    """


def add_xref(conn: psycopg.Connection, sym_id: int, source: str, value: str) -> None:
    """Attach an external id to an instrument (idempotent for the SAME instrument).

    Raises :class:`XrefConflictError` when the (source, value) already maps to a
    different sym_id — an identity collision needs an operator, not a no-op.
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
    """Find-or-create an instrument by its external ids; return its sym_id.

    If any supplied xref already maps to an instrument, that sym_id is returned
    (and any new xrefs are attached) — so identity is stable and idempotent.
    Otherwise a new instrument is created with all the xrefs, atomically (a crash
    between the instrument INSERT and its xrefs would mint exactly the orphan the
    bridge check flags).

    Raises ``ValueError`` when called with no xrefs (every call would mint a new
    instrument — duplicate identities), and :class:`XrefConflictError` when the
    supplied xrefs resolve to TWO different existing instruments (an identity-merge
    conflict must not be settled by dict ordering).
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


@dataclass
class BackfillSummary:
    created: int = 0
    existed: int = 0
    conflicts: list[str] = None  # type: ignore[assignment]  # set in backfill

    def __post_init__(self) -> None:
        if self.conflicts is None:
            self.conflicts = []


def backfill_equity_instruments(conn: psycopg.Connection) -> BackfillSummary:
    """Map every `securities` row to an `instrument(kind='equity')` (additive, idempotent).

    Creates one instrument per security not yet mapped, with the current company
    name + the security's currency/status, and a ``composite_figi`` xref. Existing
    mappings are left untouched.
    """
    conn.autocommit = True
    # Predicate matches the bridge CHECK exactly (xref must resolve to kind='equity'):
    # a composite_figi xref pointing at a non-equity instrument is a state the check
    # flags — the backfill must see it as unmapped, not skip it forever. LIMIT 1 on
    # the name subquery: duplicate current names must not abort the whole backfill.
    rows = conn.execute(
        """
        SELECT s.composite_figi, s.currency_code, s.status,
               (SELECT n.name FROM security_names n
                 WHERE n.composite_figi = s.composite_figi AND n.valid_to IS NULL
                 LIMIT 1) AS name
          FROM securities s
         WHERE NOT EXISTS (
             SELECT 1 FROM instrument_xref x
              JOIN instrument i ON i.sym_id = x.sym_id AND i.kind = %s
              WHERE x.source = %s AND x.value = s.composite_figi
         )
         ORDER BY s.composite_figi
        """,
        (EQUITY, SRC_COMPOSITE_FIGI),
    ).fetchall()
    summary = BackfillSummary()
    for figi, currency, status, name in rows:
        try:
            ensure_instrument(
                conn, EQUITY, name=name, currency_code=currency, status=status,
                xrefs={SRC_COMPOSITE_FIGI: figi},
            )
        except XrefConflictError as exc:
            # e.g. the figi's xref points at a non-equity instrument — loud + isolated
            # (one pathological row must not abort the rest of the backfill).
            summary.conflicts.append(f"{figi}: {exc}")
            continue
        summary.created += 1
    summary.existed = conn.execute(
        "SELECT count(*) FROM instrument WHERE kind = %s", (EQUITY,)
    ).fetchone()[0] - summary.created
    return summary
