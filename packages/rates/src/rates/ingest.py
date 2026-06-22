"""Load BoE curve points into ``rates.curve_point`` (immutable first-published + restated latest).

Mirrors ``sym.fx.ingest.fill_fx``: tail-since-latest vs explicit-window backfill, a plausibility
band that routes gross-corruption prints to a review queue instead of landing them, and a per-day
atomic insert. Two vintages live in one row — ``first_value`` (immutable) + ``value`` (restated).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import psycopg

from .sources.boe import CurvePoint

# Gross-corruption band: a day-over-day move (percentage points) beyond this for one tenor is a
# decimal shift / inverted feed / bad print, not a real move. Routes to review, not the store.
MAX_DAILY_MOVE_PP = 5.0

_SeriesKey = tuple[str, str, str, float]  # (curve_set, basis, rate_type, tenor)


@dataclass
class CurveLoadSummary:
    inserted: int = 0
    restated: int = 0
    skipped_existing: int = 0
    flagged: int = 0
    gated_days: list[str] = field(default_factory=list)  # days skipped as desynced (tail case)
    flagged_samples: list[str] = field(default_factory=list)
    days: int = 0
    start_date: date | None = None
    end_date: date | None = None


def _series_key(p: CurvePoint) -> _SeriesKey:
    return (p.curve_set, p.basis, p.rate_type, p.tenor)


def _latest_before(conn: psycopg.Connection, window_start: date) -> dict[_SeriesKey, float]:
    """Latest stored value per series strictly before the load window (plausibility seed)."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (curve_set, basis, rate_type, tenor)
               curve_set, basis, rate_type, tenor, value
          FROM rates.curve_point
         WHERE as_of_date < %(ws)s
         ORDER BY curve_set, basis, rate_type, tenor, as_of_date DESC
        """,
        {"ws": window_start},
    ).fetchall()
    return {(r[0], r[1], r[2], float(r[3])): float(r[4]) for r in rows}


def fill_curve(
    conn: psycopg.Connection,
    source,
    *,
    end_date: date | None = None,
    start_date: date | None = None,
    band_pp: float = MAX_DAILY_MOVE_PP,
    tail: bool | None = None,
) -> CurveLoadSummary:
    """Fetch from ``source`` and upsert. The tail (latest-bundle) load gates desynced current days;
    a backfill (full-history archive) inserts legitimately-partial history. ``tail`` defaults to
    ``start_date is None`` but the caller passes it explicitly so ``--archive`` (full history, no
    ``--start_date``) is NOT gated as a tail."""
    pts: list[CurvePoint] = source.fetch(start_date=start_date, end_date=end_date)
    summary = CurveLoadSummary()
    if not pts:
        return summary

    pts.sort(key=lambda p: (p.as_of_date, p.curve_set, p.basis, p.rate_type, p.tenor))
    window_start = pts[0].as_of_date
    summary.start_date = window_start
    summary.end_date = pts[-1].as_of_date

    prev: dict[_SeriesKey, float] = _latest_before(conn, window_start)

    by_day: dict[date, list[CurvePoint]] = defaultdict(list)
    for p in pts:
        by_day[p.as_of_date].append(p)

    # Desync gate (tail case only): the expected basis-set = what the most complete recent day has.
    expected_pairs: set[tuple[str, str]] = set()
    tail_case = (start_date is None) if tail is None else tail
    if tail_case:
        expected_pairs = max(
            ({(p.curve_set, p.basis) for p in day_pts} for day_pts in by_day.values()),
            key=len,
            default=set(),
        )

    for day in sorted(by_day):
        day_pts = by_day[day]
        if tail_case and expected_pairs:
            present = {(p.curve_set, p.basis) for p in day_pts}
            if not expected_pairs.issubset(present):
                summary.gated_days.append(day.isoformat())
                continue  # desynced partial current day — skip, don't land half a curve

        with conn.transaction():  # per-day atomicity
            for p in day_pts:
                key = _series_key(p)
                base = prev.get(key)
                if base is not None and abs(p.value - base) > band_pp:
                    conn.execute(
                        """
                        INSERT INTO rates.curve_point_review
                            (curve_set, basis, rate_type, tenor, as_of_date, value, prev_value,
                             reason, source)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (curve_set, basis, rate_type, tenor, as_of_date) DO NOTHING
                        """,
                        (p.curve_set, p.basis, p.rate_type, p.tenor, p.as_of_date, p.value, base,
                         f"move {abs(p.value - base):.2f}pp > {band_pp}pp", source.SOURCE),
                    )
                    summary.flagged += 1
                    if len(summary.flagged_samples) < 10:
                        summary.flagged_samples.append(
                            f"{p.curve_set}/{p.basis}/{p.rate_type}/{p.tenor}y {day}: "
                            f"{base:.2f}->{p.value:.2f}"
                        )
                    continue

                cur = conn.execute(
                    """
                    INSERT INTO rates.curve_point
                        (curve_set, basis, rate_type, tenor, as_of_date, value, first_value, source)
                    VALUES (%(cs)s,%(b)s,%(rt)s,%(t)s,%(d)s,%(v)s,%(v)s,%(src)s)
                    ON CONFLICT (curve_set, basis, rate_type, tenor, as_of_date) DO UPDATE
                       SET value = EXCLUDED.value,
                           last_changed_at = now(),
                           source = EXCLUDED.source
                     WHERE rates.curve_point.value IS DISTINCT FROM EXCLUDED.value
                    RETURNING (xmax = 0) AS inserted
                    """,
                    {"cs": p.curve_set, "b": p.basis, "rt": p.rate_type, "t": p.tenor,
                     "d": p.as_of_date, "v": p.value, "src": source.SOURCE},
                ).fetchone()
                if cur is None:
                    summary.skipped_existing += 1  # equal-value re-ingest (WHERE blocked update)
                elif cur[0]:
                    summary.inserted += 1
                else:
                    summary.restated += 1
                prev[key] = p.value  # within-batch chaining
        summary.days += 1

    return summary
