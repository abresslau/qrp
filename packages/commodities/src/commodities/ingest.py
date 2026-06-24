"""Load commodity price points into ``commodities.price_daily``.

Mirrors ``rates.ingest.fill_curve``: two immutable+restated vintages in one row (``first_settle``
immutable / PIT, ``settle`` restated), per-day atomic upsert. Unlike rates there is NO plausibility
band by default — commodity front-month series are genuinely volatile (front-month WTI printed
NEGATIVE in Apr-2020), so banding would reject real moves. The band is available but opt-in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import psycopg

from .sources.base import PricePoint


@dataclass
class PriceLoadSummary:
    inserted: int = 0
    restated: int = 0
    skipped_existing: int = 0
    flagged: int = 0
    flagged_samples: list[str] = field(default_factory=list)
    days: int = 0
    start_date: date | None = None
    end_date: date | None = None
    codes: list[str] = field(default_factory=list)


def fill_prices(
    conn: psycopg.Connection,
    source,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    band_pct: float | None = None,
) -> PriceLoadSummary:
    """Fetch from ``source`` and upsert. ``band_pct`` (e.g. 0.5 = 50%) routes a day-over-day move
    beyond the band to a review table instead of landing it; ``None`` (default) disables banding."""
    pts: list[PricePoint] = source.fetch(start_date=start_date, end_date=end_date)
    summary = PriceLoadSummary()
    if not pts:
        return summary
    pts.sort(key=lambda p: (p.as_of_date, p.commodity_code, p.series_type))
    summary.start_date = pts[0].as_of_date
    summary.end_date = pts[-1].as_of_date
    summary.codes = sorted({p.commodity_code for p in pts})

    # plausibility seed: latest stored settle per series strictly before the window.
    prev: dict[tuple[str, str], float] = {}
    if band_pct is not None:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (commodity_code, series_type)
                   commodity_code, series_type, settle
              FROM commodities.price_daily
             WHERE as_of_date < %s AND commodity_code = ANY(%s)
             ORDER BY commodity_code, series_type, as_of_date DESC
            """,
            (summary.start_date, summary.codes),
        ).fetchall()
        prev = {(r[0], r[1]): float(r[2]) for r in rows}

    by_day: dict[date, list[PricePoint]] = defaultdict(list)
    for p in pts:
        by_day[p.as_of_date].append(p)

    for day in sorted(by_day):
        with conn.transaction():  # per-day atomicity
            for p in by_day[day]:
                key = (p.commodity_code, p.series_type)
                base = prev.get(key)
                if (
                    band_pct is not None
                    and base not in (None, 0)
                    and abs(p.settle - base) / abs(base) > band_pct
                ):
                    conn.execute(
                        """
                        INSERT INTO commodities.price_review
                            (commodity_code, series_type, as_of_date, settle,
                             prev_settle, reason, source)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (commodity_code, series_type, as_of_date) DO NOTHING
                        """,
                        (p.commodity_code, p.series_type, p.as_of_date, p.settle, base,
                         f"move {abs(p.settle - base) / abs(base) * 100:.0f}% "
                         f"> {band_pct * 100:.0f}%",
                         source.SOURCE),
                    )
                    summary.flagged += 1
                    if len(summary.flagged_samples) < 10:
                        summary.flagged_samples.append(
                            f"{p.commodity_code} {day}: {base:.2f}->{p.settle:.2f}"
                        )
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO commodities.price_daily
                        (commodity_code, series_type, as_of_date, open, high, low, settle, volume,
                         first_settle, source)
                    VALUES (%(c)s,%(st)s,%(d)s,%(o)s,%(h)s,%(l)s,%(s)s,%(v)s,%(s)s,%(src)s)
                    ON CONFLICT (commodity_code, series_type, as_of_date) DO UPDATE
                       SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                           settle = EXCLUDED.settle, volume = EXCLUDED.volume,
                           last_changed_at = now(), source = EXCLUDED.source
                     WHERE (commodities.price_daily.open, commodities.price_daily.high,
                            commodities.price_daily.low, commodities.price_daily.settle,
                            commodities.price_daily.volume)
                           IS DISTINCT FROM
                           (EXCLUDED.open, EXCLUDED.high, EXCLUDED.low, EXCLUDED.settle,
                            EXCLUDED.volume)
                    RETURNING (xmax = 0) AS inserted
                    """,
                    {"c": p.commodity_code, "st": p.series_type, "d": p.as_of_date,
                     "o": p.open, "h": p.high, "l": p.low, "s": p.settle, "v": p.volume,
                     "src": source.SOURCE},
                ).fetchone()
                if cur is None:
                    summary.skipped_existing += 1
                elif cur[0]:
                    summary.inserted += 1
                else:
                    summary.restated += 1
                prev[key] = p.settle
        summary.days += 1
    return summary
