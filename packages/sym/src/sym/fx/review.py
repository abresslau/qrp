"""Steward the FX rejection queue (Story S.1 — FX NFR4's review surface).

A ``load_fx`` plausibility rejection persists in ``fx_rate_review``; the
steward either ACCEPTS it (the move was genuine — the rate is inserted into
``fx_rate`` through the same immutable-insert discipline, after which the
band's ``prev`` advances naturally on the next load, un-wedging it) or
REJECTS it (vendor garbage — closed, nothing stored). Closing frees the
one-open-row key, so a recurrence re-queues fresh.
"""

from __future__ import annotations

import psycopg


class FxReviewError(Exception):
    """A steward action that cannot proceed (unknown row, already resolved)."""


def list_fx_reviews(conn: psycopg.Connection, *, include_resolved: bool = False) -> list[dict]:
    """Rejection rows for the steward (open only by default)."""
    sql = (
        "SELECT review_id, quote_currency, as_of_date, rate, prior_rate, "
        "relative_move, source, reason, resolution, created_at "
        "FROM fx_rate_review"
    )
    if not include_resolved:
        sql += " WHERE NOT reviewed"
    sql += " ORDER BY review_id"
    cols = ["review_id", "quote_currency", "as_of_date", "rate", "prior_rate",
            "relative_move", "source", "reason", "resolution", "created_at"]
    return [dict(zip(cols, row, strict=True)) for row in conn.execute(sql).fetchall()]


def resolve_fx_review(
    conn: psycopg.Connection, review_id: int, *, accept: bool
) -> tuple[str, bool]:
    """Close one rejection; accepting inserts the rate into ``fx_rate``.

    Returns ``(resolution, rate_inserted)`` — the second element is HONEST:
    ``fx_rate`` stays immutable-insert, so accepting a key that meanwhile
    gained a stored rate closes the row WITHOUT landing the steward's value
    (the stored rate wins), and callers must say so rather than claim an
    insertion that never happened.

    Atomic; the row is re-read INSIDE the transaction (a concurrent load's
    refresh can't swap the rate between read and insert) and the close guards
    ``NOT reviewed``. Accepting a ``non_positive`` rejection is refused up
    front — ``fx_rate``'s ``rate > 0`` CHECK makes it impossible; only
    ``--reject`` applies. Steward accepts should proceed OLDEST-FIRST: the
    first accepted rate un-wedges the band, after which the next load stores
    the later days itself and SUPERSEDES their queued rows.
    """
    resolution = "accepted" if accept else "rejected"
    rate_inserted = False
    with conn.transaction():
        row = conn.execute(
            "SELECT quote_currency, as_of_date, rate, source, reason, reviewed "
            "FROM fx_rate_review WHERE review_id = %s",
            (review_id,),
        ).fetchone()
        if row is None:
            raise FxReviewError(f"no fx review row {review_id}")
        quote_currency, as_of_date, rate, source, reason, reviewed = row
        if reviewed:
            raise FxReviewError(f"fx review {review_id} already resolved")
        if accept and (reason == "non_positive" or rate <= 0):
            raise FxReviewError(
                f"fx review {review_id} holds a non-positive rate ({rate}) — "
                "fx_rate's rate > 0 CHECK makes accepting impossible; --reject it"
            )
        if accept:
            try:
                landed = conn.execute(
                    "INSERT INTO fx_rate "
                    "    (base_currency, quote_currency, as_of_date, rate, source) "
                    "VALUES ('USD', %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING RETURNING quote_currency",
                    (quote_currency, as_of_date, rate, source),
                ).fetchone()
            except psycopg.Error as exc:
                # e.g. the currency FK — a rejected observation for a currency
                # not in the reference table can't be accepted into fx_rate.
                # The transaction rolls back; the row STAYS OPEN.
                raise FxReviewError(
                    f"cannot accept fx review {review_id}: {exc}"
                ) from exc
            rate_inserted = landed is not None
        closed = conn.execute(
            "UPDATE fx_rate_review "
            "   SET reviewed = TRUE, resolution = %s, reviewed_at = now() "
            " WHERE review_id = %s AND NOT reviewed "
            "RETURNING review_id",
            (resolution, review_id),
        ).fetchone()
        if closed is None:
            raise FxReviewError(f"fx review {review_id} was resolved concurrently")
    return resolution, rate_inserted
