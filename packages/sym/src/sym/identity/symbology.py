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


def _insert_symbology(
    conn: psycopg.Connection,
    *,
    composite_figi: str,
    symbol_type: str,
    symbol_value: str,
    mic: str | None,
    country_iso: str | None,
    valid_from: date,
) -> None:
    # Guard against re-inserting an identical currently-effective row (the
    # EXCLUDE constraint would otherwise reject the overlap on a re-run).
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
    if holder is not None:
        if holder[0] != composite_figi:
            raise SymbologyCollisionError(
                f"{symbol_type} {symbol_value!r}@{mic} is currently held by "
                f"{holder[0]}, refusing to attach to {composite_figi} "
                "(recycled identifier — close the old row first)"
            )
        return  # identical open row — idempotent re-run
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
        _insert_symbology(
            conn,
            composite_figi=composite_figi,
            symbol_type="ticker",
            symbol_value=seed.ticker,
            mic=seed.mic,
            country_iso=country_iso,
            valid_from=valid_from,
        )
    if seed.isin:
        _insert_symbology(
            conn,
            composite_figi=composite_figi,
            symbol_type="isin",
            symbol_value=seed.isin,
            mic=None,
            country_iso=None,
            valid_from=valid_from,
        )

    return inserted is not None
