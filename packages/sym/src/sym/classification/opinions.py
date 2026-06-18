"""Multi-source GICS opinion matrix — every source's OWN classification per company.

``gics_scd`` holds the ONE precedence-resolved classification per security (the truth the
heatmap + ``validate`` consume). This module is additive and orthogonal: it records EVERY
source's opinion of EVERY company into ``gics_source_opinion`` (SCD, keyed on
``(composite_figi, source)``), so the detail view can show "what each source says" and
disagreement is visible. It never touches ``gics_scd`` — a bug here cannot corrupt the
resolved classification.

The writer mirrors :func:`sym.classification.gics.apply_classifications`'s SCD discipline
(per-row transaction, close+insert on a later-day change, same-day update-in-place,
unchanged no-op) but is keyed per-source and carries NO precedence logic — each source's
opinion stands on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import psycopg

from sym.classification.gics import GicsClassification


@dataclass
class OpinionSummary:
    """What one source's opinion pass wrote into the matrix."""

    source: str
    in_scope: int = 0
    classified: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_closed: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def _current_opinion(
    conn: psycopg.Connection, composite_figi: str, source: str
) -> tuple[tuple[str | None, str | None, str | None, str | None], date] | None:
    """The currently-effective ``(level_names, valid_from)`` for ``(figi, source)``, or None."""
    row = conn.execute(
        """
        SELECT sector_name, industry_group_name, industry_name, sub_industry_name, valid_from
          FROM gics_source_opinion
         WHERE composite_figi = %s AND source = %s AND valid_to IS NULL
        """,
        (composite_figi, source),
    ).fetchone()
    if row is None:
        return None
    return (tuple(row[:4]), row[4])


def _insert_opinion(
    conn: psycopg.Connection, c: GicsClassification, *, valid_from: date
) -> None:
    conn.execute(
        """
        INSERT INTO gics_source_opinion
            (composite_figi, source, sector_code, sector_name,
             industry_group_code, industry_group_name,
             industry_code, industry_name,
             sub_industry_code, sub_industry_name, valid_from)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            c.composite_figi, c.source, c.sector_code, c.sector_name,
            c.industry_group_code, c.industry_group_name,
            c.industry_code, c.industry_name,
            c.sub_industry_code, c.sub_industry_name, valid_from,
        ),
    )


def _update_opinion_in_place(conn: psycopg.Connection, c: GicsClassification) -> None:
    conn.execute(
        """
        UPDATE gics_source_opinion
           SET sector_code = %s, sector_name = %s,
               industry_group_code = %s, industry_group_name = %s,
               industry_code = %s, industry_name = %s,
               sub_industry_code = %s, sub_industry_name = %s
         WHERE composite_figi = %s AND source = %s AND valid_to IS NULL
        """,
        (
            c.sector_code, c.sector_name,
            c.industry_group_code, c.industry_group_name,
            c.industry_code, c.industry_name,
            c.sub_industry_code, c.sub_industry_name,
            c.composite_figi, c.source,
        ),
    )


def apply_source_opinions(
    conn: psycopg.Connection,
    plans: Sequence[GicsClassification],
    *,
    as_of_date: date | None = None,
) -> OpinionSummary:
    """Write one source's opinions into ``gics_source_opinion`` (SCD, per (figi, source)).

    Every plan must carry the SAME ``source`` (one pass = one source). Idempotent: an
    unchanged opinion is a no-op; a changed one on a later day closes the prior row and
    inserts; a same-day change updates in place (a zero-width period would violate the
    validity CHECK). Each row writes in its own transaction — one bad row never halts the
    rest. Returns the per-source :class:`OpinionSummary`.
    """
    as_of_date = as_of_date or date.today()
    source = plans[0].source if plans else ""
    summary = OpinionSummary(source=source, in_scope=len(plans))
    for c in plans:
        summary.classified += 1
        try:
            with conn.transaction():
                current = _current_opinion(conn, c.composite_figi, c.source)
                if current is not None:
                    cur_levels, cur_valid_from = current
                    if cur_levels == c.level_names():
                        summary.unchanged += 1
                        continue
                    if cur_valid_from == as_of_date:
                        _update_opinion_in_place(conn, c)
                        summary.rows_updated += 1
                        continue
                    if as_of_date < cur_valid_from:
                        summary.failed += 1
                        summary.failures.append(
                            f"{c.composite_figi}/{c.source}: backdated "
                            f"({as_of_date} < current valid_from {cur_valid_from})"
                        )
                        continue
                    conn.execute(
                        "UPDATE gics_source_opinion SET valid_to = %s "
                        "WHERE composite_figi = %s AND source = %s AND valid_to IS NULL",
                        (as_of_date, c.composite_figi, c.source),
                    )
                    summary.rows_closed += 1
                _insert_opinion(conn, c, valid_from=as_of_date)
                summary.rows_inserted += 1
        except psycopg.Error as exc:
            summary.failed += 1
            summary.failures.append(
                f"{c.composite_figi}/{c.source}: {type(exc).__name__}: {str(exc)[:160]}"
            )
    return summary
