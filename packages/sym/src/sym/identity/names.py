"""Effective-dated company names (enhancement, 2026-06-06).

A company name is a drifting vendor label (Facebook -> Meta), so it is stored
SCD-shaped against the immutable CompositeFIGI in ``security_names`` — a rename
adds a row while the FIGI is unchanged. Source is OpenFIGI (captured during
resolution). The SCD write reuses the gics fix: a same-day correction updates in
place (closing would set ``valid_to = valid_from``, violating the validity CHECK);
a later rename closes the prior row before inserting the new one. Idempotent: an
unchanged name is a no-op.
"""

from __future__ import annotations

from datetime import date

import psycopg

UNCHANGED = "unchanged"
UPDATED = "updated"
INSERTED = "inserted"
REPLACED = "replaced"  # prior row closed, new row inserted (a rename)


def current_name(conn: psycopg.Connection, composite_figi: str) -> str | None:
    """The currently-effective company name for a FIGI, or None."""
    row = conn.execute(
        "SELECT name FROM security_names WHERE composite_figi = %s AND valid_to IS NULL",
        (composite_figi,),
    ).fetchone()
    return row[0] if row else None


def write_name(
    conn: psycopg.Connection,
    composite_figi: str,
    name: str,
    *,
    source: str = "openfigi",
    as_of_date: date | None = None,
) -> str:
    """Record a company name in SCD shape; returns what happened.

    Unchanged → no-op; a same-day correction → update the current row in place; a
    later rename → close the prior row (``valid_to = as_of_date``) and insert the new
    one. Mirrors the gics SCD writer (no zero-width periods, immutable history).
    """
    as_of_date = as_of_date or date.today()
    current = conn.execute(
        """
        SELECT name, valid_from FROM security_names
         WHERE composite_figi = %s AND valid_to IS NULL
        """,
        (composite_figi,),
    ).fetchone()

    if current is not None and current[0] == name:
        return UNCHANGED

    if current is not None and current[1] == as_of_date:
        conn.execute(
            """
            UPDATE security_names SET name = %s, source = %s
             WHERE composite_figi = %s AND valid_to IS NULL
            """,
            (name, source, composite_figi),
        )
        return UPDATED

    if current is not None and as_of_date < current[1]:
        # Backdated write: closing the current row at as_of_date would violate the
        # valid_to > valid_from CHECK. Retro corrections need a dedicated path; an
        # explicit error beats an opaque CheckViolation escaping mid-transaction.
        raise ValueError(
            f"backdated name write for {composite_figi}: as_of_date {as_of_date} "
            f"precedes the current row's valid_from {current[1]}"
        )

    if current is not None:
        conn.execute(
            """
            UPDATE security_names SET valid_to = %s
             WHERE composite_figi = %s AND valid_to IS NULL
            """,
            (as_of_date, composite_figi),
        )

    conn.execute(
        """
        INSERT INTO security_names (composite_figi, name, source, valid_from)
        VALUES (%s, %s, %s, %s)
        """,
        (composite_figi, name, source, as_of_date),
    )
    return REPLACED if current is not None else INSERTED
