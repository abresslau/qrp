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


def resolve_fx_review(conn: psycopg.Connection, review_id: int, *, accept: bool) -> str:
    """Close one rejection; accepting inserts the rate into ``fx_rate``.

    Atomic (insert + close in one transaction); the close guards
    ``NOT reviewed`` so a concurrent resolution raises instead of silently
    double-applying. ``fx_rate`` stays immutable-insert — accepting a rate for
    a (currency, date) that meanwhile gained a stored rate is a no-op insert,
    and the row still closes (the queue item is dealt with either way).
    """
    row = conn.execute(
        "SELECT quote_currency, as_of_date, rate, source, reviewed "
        "FROM fx_rate_review WHERE review_id = %s",
        (review_id,),
    ).fetchone()
    if row is None:
        raise FxReviewError(f"no fx review row {review_id}")
    quote_currency, as_of_date, rate, source, reviewed = row
    if reviewed:
        raise FxReviewError(f"fx review {review_id} already resolved")
    resolution = "accepted" if accept else "rejected"
    with conn.transaction():
        if accept:
            try:
                conn.execute(
                    "INSERT INTO fx_rate (base_currency, quote_currency, as_of_date, rate, source) "
                    "VALUES ('USD', %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (quote_currency, as_of_date, rate, source),
                )
            except psycopg.Error as exc:
                # e.g. the currency FK — a rejected observation for a currency
                # not in the reference table can't be accepted into fx_rate.
                # The transaction rolls back; the row STAYS OPEN.
                raise FxReviewError(
                    f"cannot accept fx review {review_id}: {exc}"
                ) from exc
        closed = conn.execute(
            "UPDATE fx_rate_review "
            "   SET reviewed = TRUE, resolution = %s, reviewed_at = now() "
            " WHERE review_id = %s AND NOT reviewed "
            "RETURNING review_id",
            (resolution, review_id),
        ).fetchone()
        if closed is None:
            raise FxReviewError(f"fx review {review_id} was resolved concurrently")
    return resolution
