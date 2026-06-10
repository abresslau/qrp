"""The return-math specification (Story 3.1, FR-9 / OI-2).

This is the executable spec for sym's return windows: the time periods, how each
window's *base* and *end* sessions are anchored, and how the return is computed
(cumulative vs annualized CAGR). It is deliberately independent of price storage —
``base_date``/``end_date`` take the trading sessions (from the snapshotted
``trading_calendar``, Story 2.1) so the rules stay pure and testable. The
``fact_returns`` materialization that applies these to ``v_prices_adjusted`` is
Stories 3.4/3.5.

``kind`` is an internal *base-date computation strategy*, NOT a financial category:
every non-``calendar`` window is a trailing/rolling return (5Y trails just like 3M).
The one financially-meaningful split is ``calendar`` (period-to-date, resets at the
boundary) vs everything else (trailing). Cumulative-vs-annualized is the separate
``annualized`` flag.

  * ``calendar``  — base = the prior period-end session; end = as-of (1D, WTD, MTD,
                    QTD, YTD). Period-to-date — the only kind that resets.
  * ``session``   — base = N **trading sessions** back (5D, 10D); end = as-of.
  * ``trailing``  — base = N days/months/**years** back, snapped to the last session
                    on/before; end = as-of (1W…1Y cumulative; 2Y…30Y as cumulative
                    totals or ``*_ANN`` CAGRs — same endpoints, different expression).
  * ``inception`` — base = first available close; end = as-of (``SI_ANN`` CAGR or
                    ``SI`` cumulative). "Since inception" — general (an index/fund
                    has an inception date, not an IPO).
  * ``period``    — a **discrete** completed calendar period: BOTH endpoints in the
                    past (end = last session of the just-finished period, base = the
                    period before it). PQ = the just-completed quarter's return.

Window ids are a **stable PK** (``fact_returns.window_id``); new windows are
*appended* (5D/10D=19/20, cumulative multi-year + SI=21–27, PQ=28), never
renumbered, so existing materialized rows stay valid. Iteration order is irrelevant
— only the id matters.

NULL rule (FR-9): if the base date can't be resolved because history doesn't reach
the target, the window is undefined — ``base_date`` returns ``None`` and the loader
writes NULL.

Total return (EXDATE_C): the TR series reinvests each dividend on its **ex-date**,
gross (no withholding). PR uses the split-only-adjusted series, TR the
split+dividend-reinvested series; both are evaluated over these same windows. The
ex-date reinvestment is applied when Story 3.5 builds the TR series.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

CALENDAR = "calendar"
SESSION = "session"
TRAILING = "trailing"
INCEPTION = "inception"
PERIOD = "period"

DAYS_PER_YEAR = Decimal("365.25")

# EXDATE_C: dividends are reinvested on their ex-date, gross (Story 3.5 applies it).
TR_REINVESTMENT = "EXDATE_C"


@dataclass(frozen=True)
class Window:
    """One return window. ``id`` is the stable key (fact_returns.window_id)."""

    id: int
    code: str
    label: str
    kind: str
    period: str | None = None  # calendar/period: day|week|month|quarter|year
    sessions: int | None = None  # session: lookback in trading days (5D, 10D)
    days: int | None = None  # trailing: lookback in days (1W)
    months: int | None = None  # trailing: lookback in months
    years: int | None = None  # trailing: lookback in years
    annualized: bool = False


# The return windows (FR-9). Calendar-to-date, then trailing (sub-year cumulative,
# then multi-year — annualized *_ANN and cumulative siblings), then since-inception, then
# the discrete prior-period window. 5D/10D/the cumulative multi-year/PQ are appended
# (ids 19+) so ids stay stable. 1W is trailing one-week (distinct from WTD = calendar
# week-to-date, and from 5D = 5 trading sessions).
WINDOWS: tuple[Window, ...] = (
    Window(1, "1D", "1 day", CALENDAR, period="day"),
    Window(2, "WTD", "Week to date", CALENDAR, period="week"),
    Window(3, "MTD", "Month to date", CALENDAR, period="month"),
    Window(4, "QTD", "Quarter to date", CALENDAR, period="quarter"),
    Window(5, "YTD", "Year to date", CALENDAR, period="year"),
    Window(6, "1W", "1 week", TRAILING, days=7),
    Window(7, "1M", "1 month", TRAILING, months=1),
    Window(8, "3M", "3 months", TRAILING, months=3),
    Window(9, "6M", "6 months", TRAILING, months=6),
    Window(10, "9M", "9 months", TRAILING, months=9),
    Window(11, "1Y", "1 year", TRAILING, months=12),
    Window(12, "2Y_ANN", "2 years annualized", TRAILING, years=2, annualized=True),
    Window(13, "3Y_ANN", "3 years annualized", TRAILING, years=3, annualized=True),
    Window(14, "5Y_ANN", "5 years annualized", TRAILING, years=5, annualized=True),
    Window(15, "10Y_ANN", "10 years annualized", TRAILING, years=10, annualized=True),
    Window(16, "20Y_ANN", "20 years annualized", TRAILING, years=20, annualized=True),
    Window(17, "30Y_ANN", "30 years annualized", TRAILING, years=30, annualized=True),
    Window(18, "SI_ANN", "Since inception annualized", INCEPTION, annualized=True),
    Window(19, "5D", "5 trading days", SESSION, sessions=5),
    Window(20, "10D", "10 trading days", SESSION, sessions=10),
    # Cumulative (NOT annualized) multi-year + since-inception totals — the total-
    # return siblings of the *_ANN windows above (same endpoints; ratio-1 vs CAGR).
    Window(21, "2Y", "2 years", TRAILING, years=2),
    Window(22, "3Y", "3 years", TRAILING, years=3),
    Window(23, "5Y", "5 years", TRAILING, years=5),
    Window(24, "10Y", "10 years", TRAILING, years=10),
    Window(25, "20Y", "20 years", TRAILING, years=20),
    Window(26, "30Y", "30 years", TRAILING, years=30),
    Window(27, "SI", "Since inception", INCEPTION),
    # Discrete prior period: the just-completed calendar quarter's return (both
    # endpoints in the past — see end_date). PQ = the Q3 return once Q4 begins.
    Window(28, "PQ", "Last completed quarter", PERIOD, period="quarter"),
)

BY_CODE: dict[str, Window] = {w.code: w for w in WINDOWS}


# --- calendar period starts -------------------------------------------------


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _year_start(d: date) -> date:
    return date(d.year, 1, 1)


_PERIOD_START = {
    "week": _week_start,
    "month": _month_start,
    "quarter": _quarter_start,
    "year": _year_start,
}


def _minus_months(d: date, months: int) -> date:
    total = (d.year * 12 + (d.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    # clamp the day to the target month's length (e.g. Mar 31 - 1mo -> Feb 28/29)
    next_month_first = date(year + (month // 12), (month % 12) + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _minus_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year - years, day=28)


# --- session lookups --------------------------------------------------------


def _last_on_or_before(sessions: Sequence[date], target: date) -> date | None:
    i = bisect.bisect_right(sessions, target)
    return sessions[i - 1] if i > 0 else None


def _session_before(sessions: Sequence[date], as_of_date: date) -> date | None:
    i = bisect.bisect_left(sessions, as_of_date)
    return sessions[i - 1] if i > 0 else None


def _completed_period_end(window: Window, as_of_date: date, sessions: Sequence[date]) -> date | None:
    """Last session of the calendar period that ended just before ``as_of_date``'s period.

    Shared by ``calendar`` windows (their base) and ``period`` windows (their end).
    """
    period_start = _PERIOD_START[window.period](as_of_date)
    return _last_on_or_before(sessions, period_start - timedelta(days=1))


def base_date(window: Window, as_of_date: date, sessions: Sequence[date]) -> date | None:
    """The base (start) session for ``window`` as of ``as_of_date``.

    ``sessions`` is the ascending list of trading days for the security's exchange.
    Returns ``None`` when history doesn't reach the base (the NULL rule).
    """
    if window.kind == CALENDAR:
        if window.period == "day":
            return _session_before(sessions, as_of_date)
        return _completed_period_end(window, as_of_date, sessions)
    if window.kind == SESSION:
        # N sessions back from as_of_date's position; i-1 is the prior session (matching
        # 1D when sessions==1), so i-N is N sessions back. None if history is short.
        i = bisect.bisect_left(sessions, as_of_date)
        j = i - window.sessions
        return sessions[j] if j >= 0 else None
    if window.kind == TRAILING:
        if window.days is not None:
            target = as_of_date - timedelta(days=window.days)
        elif window.months is not None:
            target = _minus_months(as_of_date, window.months)
        else:
            target = _minus_years(as_of_date, window.years)
        return _last_on_or_before(sessions, target)
    if window.kind == INCEPTION:
        return sessions[0] if sessions else None
    if window.kind == PERIOD:
        # base = the close of the period BEFORE the just-completed one, so the
        # return spans exactly the completed period (e.g. PQ = Q3-end / Q2-end - 1).
        end = _completed_period_end(window, as_of_date, sessions)
        if end is None:
            return None
        prior_start = _PERIOD_START[window.period](end)
        return _last_on_or_before(sessions, prior_start - timedelta(days=1))
    raise ValueError(f"unknown window kind {window.kind!r}")


def end_date(window: Window, as_of_date: date, sessions: Sequence[date]) -> date | None:
    """The end (numerator) session for ``window`` as of ``as_of_date``.

    For nearly all kinds the return ends at ``as_of_date`` itself (a base->as-of return).
    A ``period`` window is discrete: it ends at the last session of the just-completed
    calendar period (e.g. PQ ends at the prior quarter's last session), so both of its
    endpoints lie in the past.
    """
    if window.kind == PERIOD:
        return _completed_period_end(window, as_of_date, sessions)
    return as_of_date


def period_years(as_of_date: date, base: date) -> Decimal:
    """Actual elapsed years between base and as_of_date (for CAGR annualization)."""
    return Decimal((as_of_date - base).days) / DAYS_PER_YEAR


def canonical_return(
    price_asof: Decimal,
    price_base: Decimal,
    *,
    annualized: bool,
    years: Decimal | None = None,
) -> Decimal | None:
    """The window return: cumulative ``ratio - 1``, or CAGR over ``years``.

    Returns ``None`` if an endpoint price is missing or non-positive (NULL rule — a
    non-positive price is corrupt data, and ``ratio.ln()`` would raise on it). CAGR uses
    Decimal ln/exp for determinism.
    """
    if price_base is None or price_base <= 0 or price_asof is None or price_asof <= 0:
        return None
    ratio = price_asof / price_base
    if not annualized:
        return ratio - 1
    if not years or years <= 0:
        return None
    return (ratio.ln() / years).exp() - 1
