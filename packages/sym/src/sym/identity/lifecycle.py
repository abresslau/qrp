"""Security lifecycle: soft-delete (delisting) and survivorship-safe filtering (Story 1.7).

A delisted security is never physically removed — the row, its CompositeFIGI, and
all effective-dated symbology/price history stay intact. Delisting is a *status*
change plus a ``delist_date`` stamp, so historical returns remain reproducible
(survivorship invariant). Callers must opt in to seeing delisted rows; the default
listing is active-only, but that filter is explicit and never silent.
"""

from __future__ import annotations

from datetime import date

import psycopg

# securities.status domain (matches the status_chk CHECK constraint).
ACTIVE = "active"
DELISTED = "delisted"
SUSPENDED = "suspended"


def delist_security(
    conn: psycopg.Connection,
    composite_figi: str,
    *,
    delist_date: date,
    status: str = DELISTED,
) -> bool:
    """Soft-delete a security: stamp its terminal status and ``delist_date``.

    Returns True if a row was updated, False if no security had that CompositeFIGI.
    Never deletes the row — history (symbology, prices) is retained by design.
    The ``active`` status is rejected because an active security has no delist date
    (the ``active_no_delist_chk`` constraint would reject the write anyway).
    """
    if status == ACTIVE:
        raise ValueError("delisting cannot set status to 'active'; use set_status instead")

    updated = conn.execute(
        """
        UPDATE securities
           SET status = %s, delist_date = %s
         WHERE composite_figi = %s
        RETURNING composite_figi
        """,
        (status, delist_date, composite_figi),
    ).fetchone()
    return updated is not None


def set_status(
    conn: psycopg.Connection,
    composite_figi: str,
    *,
    status: str,
) -> bool:
    """Change a security's status without touching ``delist_date``.

    Reactivating a delisted security (``status='active'``) also clears
    ``delist_date`` so the row satisfies ``active_no_delist_chk``.
    """
    clear_delist = status == ACTIVE
    updated = conn.execute(
        """
        UPDATE securities
           SET status = %s,
               delist_date = CASE WHEN %s THEN NULL ELSE delist_date END
         WHERE composite_figi = %s
        RETURNING composite_figi
        """,
        (status, clear_delist, composite_figi),
    ).fetchone()
    return updated is not None


def _active_filter(include_delisted: bool) -> str:
    """SQL WHERE clause fragment selecting the lifecycle scope.

    Active-only is the survivorship-safe default; ``include_delisted`` widens it
    to the full set. Returned as a fragment (no leading WHERE) so callers compose it.
    """
    return "TRUE" if include_delisted else "status = 'active'"


def iter_securities(
    conn: psycopg.Connection,
    *,
    include_delisted: bool = False,
) -> list[tuple[str, str, date | None]]:
    """List securities as ``(composite_figi, status, delist_date)``.

    Active-only by default; pass ``include_delisted=True`` to see the full set.
    """
    rows = conn.execute(
        f"""
        SELECT composite_figi, status, delist_date
          FROM securities
         WHERE {_active_filter(include_delisted)}
         ORDER BY composite_figi
        """
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def count_securities(
    conn: psycopg.Connection,
    *,
    include_delisted: bool = False,
) -> int:
    """Count securities in the requested lifecycle scope (active-only by default)."""
    row = conn.execute(
        f"SELECT count(*) FROM securities WHERE {_active_filter(include_delisted)}"
    ).fetchone()
    return row[0] if row else 0
