"""Freshness classification for sym data areas.

Honest 3-state vocabulary (matches the console status system): ``ok`` / ``stale`` /
``unknown``. Each area reports its own ``as_of_date`` date and how many days it sits behind the
latest trading session we have prices for (the best "current" proxy QRP has without
recomputing sym's calendar logic).

NOTE (architecture): a calendar-aware "expected session" is sym's authority, not QRP's —
this day-count proxy is the v1 stand-in until sym exposes an expected-session signal. We
never claim freshness we can't source; ``unknown`` is shown when an area has no data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Days behind the latest session before an area is flagged stale. Slow-cadence areas
# (fundamentals) legitimately lag; this is a coarse, honest proxy, not sym's calendar.
STALE_AFTER_DAYS = 4


@dataclass(frozen=True)
class AreaFreshness:
    area: str
    as_of_date: date | None
    days_behind: int | None  # vs the latest session; None when unknown
    status: str  # "ok" | "stale" | "unknown"


def classify(area: str, as_of_date: date | None, latest_session: date | None) -> AreaFreshness:
    if as_of_date is None:
        return AreaFreshness(area, None, None, "unknown")
    if latest_session is None:
        return AreaFreshness(area, as_of_date, None, "unknown")
    days_behind = max(0, (latest_session - as_of_date).days)
    status = "stale" if days_behind > STALE_AFTER_DAYS else "ok"
    return AreaFreshness(area, as_of_date, days_behind, status)
