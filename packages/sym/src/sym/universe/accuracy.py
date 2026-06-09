"""Membership accuracy gate (Story U3.3, FR14 — SM-6-style for membership).

A periodic cross-check of a universe's *maintained* membership against an
**independent** second source (e.g. ETF holdings vs a Wikipedia-derived list — not
two derivatives of the same upstream). It alarms when the symmetric difference
exceeds a threshold, so a universe that is *wrong* (not merely stale) is caught.
A proxy reference (an ETF that tracks but is not the index) gets a wider tolerance
to avoid alert fatigue.

The comparison is on normalised identifier tokens (both pipelines build tokens via
``membership_diff``), so it does not depend on resolution succeeding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from sym.universe.registry import JOIN, MembershipChange

DEFAULT_THRESHOLD = 0.05
# A proxy (ETF holdings) legitimately differs from the index it tracks; widen the
# alarm tolerance for a proxy reference so normal tracking drift isn't an alarm.
DEFAULT_PROXY_TOLERANCE = 0.05


@dataclass
class AccuracyResult:
    maintained_count: int
    reference_count: int
    missing: set[str] = field(default_factory=set)  # in reference, not maintained
    extra: set[str] = field(default_factory=set)  # in maintained, not reference
    divergence: float = 0.0
    threshold: float = DEFAULT_THRESHOLD
    alarm: bool = False


def evaluate(
    maintained: set[str],
    reference: set[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    proxy_tolerance: float = 0.0,
) -> AccuracyResult:
    """Compare maintained vs reference membership; alarm on excess divergence.

    Divergence is the Jaccard distance ``|A △ B| / |A ∪ B|``. The effective
    threshold is ``threshold + proxy_tolerance`` (use ``proxy_tolerance`` when the
    reference is an ETF proxy). An empty union is zero divergence (no alarm).
    """
    missing = reference - maintained
    extra = maintained - reference
    union = maintained | reference
    divergence = (len(missing) + len(extra)) / len(union) if union else 0.0
    effective = threshold + proxy_tolerance
    return AccuracyResult(
        maintained_count=len(maintained),
        reference_count=len(reference),
        missing=missing,
        extra=extra,
        divergence=divergence,
        threshold=effective,
        alarm=divergence > effective,
    )


def current_tokens_from_changes(changes: Iterable[MembershipChange]) -> set[str]:
    """The current member-token set implied by a snapshot source's join events.

    A snapshot source (ETF holdings, a current Wikipedia table) emits ``join`` for
    every current member; this collects them as the reference set.
    """
    return {c.raw_identifier for c in changes if c.change == JOIN}


def maintained_tokens(conn: psycopg.Connection, universe_id: str) -> set[str]:
    """The current maintained member tokens (open intervals) for a universe."""
    rows = conn.execute(
        """
        SELECT DISTINCT raw_identifier
          FROM universe_membership
         WHERE universe_id = %s AND valid_to IS NULL AND raw_identifier IS NOT NULL
        """,
        (universe_id,),
    ).fetchall()
    return {r[0] for r in rows}


def run_accuracy_check(
    conn: psycopg.Connection,
    universe_id: str,
    reference: set[str],
    *,
    reference_source: str,
    as_of_date: date,
    threshold: float = DEFAULT_THRESHOLD,
    proxy_tolerance: float = 0.0,
    sample: int = 20,
) -> AccuracyResult:
    """Cross-check maintained membership vs an independent ``reference`` set.

    Writes a ``universe_accuracy_check`` audit row and returns the result. The
    detail JSON carries a bounded sample of the missing/extra members.
    """
    conn.autocommit = True
    maintained = maintained_tokens(conn, universe_id)
    result = evaluate(
        maintained, reference, threshold=threshold, proxy_tolerance=proxy_tolerance
    )
    detail = {
        "missing_sample": sorted(result.missing)[:sample],
        "extra_sample": sorted(result.extra)[:sample],
    }
    conn.execute(
        """
        INSERT INTO universe_accuracy_check
            (universe_id, as_of_date, reference_source, maintained_count, reference_count,
             missing, extra, divergence, threshold, alarm, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            universe_id, as_of_date, reference_source, result.maintained_count,
            result.reference_count, len(result.missing), len(result.extra),
            result.divergence, result.threshold, result.alarm, Jsonb(detail),
        ),
    )
    return result


def accuracy_alarms(conn: psycopg.Connection) -> list[dict]:
    """The latest accuracy check per universe where it alarmed (for the digest)."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (universe_id)
               universe_id, checked_at, reference_source, divergence, threshold,
               missing, extra
          FROM universe_accuracy_check
         ORDER BY universe_id, checked_at DESC
        """
    ).fetchall()
    cols = ["universe_id", "checked_at", "reference_source", "divergence", "threshold",
            "missing", "extra"]
    return [dict(zip(cols, r, strict=True)) for r in rows if r[3] > r[4]]
