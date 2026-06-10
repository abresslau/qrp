"""Writes to ``securities`` and effective-dated ``security_symbology`` (FR-2, FR-3).

A clean FIGI assignment produces one ``securities`` row (keyed on CompositeFIGI)
plus the currently-effective identifier rows that resolve to it. Trading currency
and country are looked up from the ``exchange`` reference table for the listing
MIC, so they are never guessed. Writes are idempotent: re-running resolution
neither clobbers an existing security nor duplicates an open symbology row.
"""

from __future__ import annotations

from datetime import date

import psycopg

from sym.identity.universe import SeedSecurity


class SymbologyCollisionError(Exception):
    """An open symbology row for (type, value, mic) belongs to a different security."""


class SymbologyTransitionError(Exception):
    """A transition that needs operator surgery: backdated write or same-day drift."""


class ExchangeLookupError(LookupError):
    """The listing MIC is absent from the exchange reference table."""


def _exchange_facts(conn: psycopg.Connection, mic: str) -> tuple[str, str]:
    """Return (currency_code, country_iso) for a listing MIC."""
    row = conn.execute(
        "SELECT currency_code, country_iso FROM exchange WHERE mic = %s",
        (mic,),
    ).fetchone()
    if row is None:
        raise ExchangeLookupError(f"MIC {mic!r} not found in exchange reference table")
    return row[0], row[1]


def _reconcile_symbology(
    conn: psycopg.Connection,
    *,
    composite_figi: str,
    symbol_type: str,
    symbol_value: str,
    mic: str | None,
    country_iso: str | None,
    valid_from: date,
) -> None:
    """Make ``(symbol_value, mic)`` the security's ONE current identifier of this type.

    The SCD transition (Story 1.10 — the data-conventions §4 SQ→XYZ semantics,
    finally implemented): a differing open row is CLOSED at ``valid_from``
    (exclusive end — the boundary day belongs to the successor) and the new row
    opened from it; a SAME-DAY change updates the row in place (close+insert
    would violate the ``valid_to > valid_from`` CHECK); an identical open row is
    the idempotent no-op it always was. Collisions take precedence: a value held
    by a DIFFERENT figi refuses loudly and changes nothing — transitions never
    steal identifiers.
    """
    # A RECYCLED identifier — the open (type, value, mic) row belonging to a
    # DIFFERENT figi — must be loud, not a silent skip: the new security would
    # quietly end up with no symbology row and no breadcrumb to why.
    holder = conn.execute(
        """
        SELECT composite_figi FROM security_symbology
         WHERE symbol_type = %s AND symbol_value = %s
           AND coalesce(mic::text, '') = coalesce(%s::text, '')
           AND valid_to IS NULL
        """,
        (symbol_type, symbol_value, mic),
    ).fetchone()
    if holder is not None and holder[0] != composite_figi:
        raise SymbologyCollisionError(
            f"{symbol_type} {symbol_value!r}@{mic} is currently held by "
            f"{holder[0]}, refusing to attach to {composite_figi} "
            "(recycled identifier — close the old row first)"
        )

    open_rows = conn.execute(
        """
        SELECT symbol_value, mic, valid_from FROM security_symbology
         WHERE composite_figi = %s AND symbol_type = %s AND valid_to IS NULL
        """,
        (composite_figi, symbol_type),
    ).fetchall()

    def _matches(value: str, row_mic: str | None) -> bool:
        return value == symbol_value and (row_mic or "") == (mic or "")

    differing = [r for r in open_rows if not _matches(r[0], r[1])]
    # Backdated write: an open row NEWER than the incoming valid_from can be
    # neither rewritten (different day) nor closed (the valid_to > valid_from
    # CHECK forbids it) — silent acceptance would mint exactly the duplicate-open
    # state the symbology_transitions check audits. Refuse: operator surgery.
    # This refusal is ALSO what keeps closed rows out of the EXCLUDE's way: a
    # non-backdated new row starts at/after every open row's valid_from, so no
    # closed range (which ends at such a boundary) can overlap it.
    later = [r for r in differing if r[2] > valid_from]
    if later:
        raise SymbologyTransitionError(
            f"{composite_figi}/{symbol_type}: open row {later[0][0]!r} starts "
            f"{later[0][2]}, AFTER the incoming valid_from {valid_from} — a "
            "backdated transition needs operator surgery, refusing"
        )
    same_day = [r for r in differing if r[2] == valid_from]
    if len(same_day) > 1:
        raise SymbologyTransitionError(
            f"{composite_figi}/{symbol_type}: {len(same_day)} duplicate-open rows "
            f"share valid_from {valid_from} — fix the drift first "
            "(see the symbology_transitions check)"
        )
    earlier = [r for r in differing if r[2] < valid_from]

    # Mutations run in one (sub)transaction: callers already wrap per-item, in
    # which case this is a savepoint; under bare autocommit it is a real txn.
    with conn.transaction():
        # Close EVERY earlier differing open row, precisely keyed — the sweep
        # runs on the idempotent path too, so pre-1.10 duplicate-open drift
        # self-heals on the next routine write of the current value.
        for old_value, old_mic, _vf in earlier:
            conn.execute(
                """
                UPDATE security_symbology
                   SET valid_to = %s
                 WHERE composite_figi = %s AND symbol_type = %s
                   AND symbol_value = %s
                   AND coalesce(mic::text, '') = coalesce(%s::text, '')
                   AND valid_to IS NULL
                """,
                (valid_from, composite_figi, symbol_type, old_value, old_mic),
            )
        if holder is not None:
            return  # identical open row — idempotent re-run (drift swept above)
        if same_day:
            # Same-day change: rewrite in place (the CHECK forbids a zero-length
            # close), keyed by the OLD identity so only that row moves.
            old_value, old_mic, _vf = same_day[0]
            conn.execute(
                """
                UPDATE security_symbology
                   SET symbol_value = %s, mic = %s, country_iso = %s
                 WHERE composite_figi = %s AND symbol_type = %s
                   AND symbol_value = %s
                   AND coalesce(mic::text, '') = coalesce(%s::text, '')
                   AND valid_to IS NULL
                """,
                (symbol_value, mic, country_iso, composite_figi, symbol_type,
                 old_value, old_mic),
            )
            return
        conn.execute(
            """
            INSERT INTO security_symbology
                (composite_figi, symbol_type, symbol_value, mic, country_iso, valid_from)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (composite_figi, symbol_type, symbol_value, mic, country_iso, valid_from),
        )


def write_security(
    conn: psycopg.Connection,
    *,
    seed: SeedSecurity,
    composite_figi: str,
    share_class_figi: str | None,
    valid_from: date | None = None,
) -> bool:
    """Write the securities row + its currently-effective symbology rows.

    Returns True if a new securities row was created, False if it already existed
    (in which case symbology rows are still reconciled). The listing MIC comes
    from the seed; currency and country are resolved from ``exchange``.
    """
    valid_from = valid_from or date.today()
    currency_code, country_iso = _exchange_facts(conn, seed.mic)

    inserted = conn.execute(
        """
        INSERT INTO securities (composite_figi, share_class_figi, mic, currency_code)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (composite_figi) DO NOTHING
        RETURNING composite_figi
        """,
        (composite_figi, share_class_figi, seed.mic, currency_code),
    ).fetchone()

    if seed.ticker:
        _reconcile_symbology(
            conn,
            composite_figi=composite_figi,
            symbol_type="ticker",
            symbol_value=seed.ticker,
            mic=seed.mic,
            country_iso=country_iso,
            valid_from=valid_from,
        )
    if seed.isin:
        _reconcile_symbology(
            conn,
            composite_figi=composite_figi,
            symbol_type="isin",
            symbol_value=seed.isin,
            mic=None,
            country_iso=None,
            valid_from=valid_from,
        )

    return inserted is not None
