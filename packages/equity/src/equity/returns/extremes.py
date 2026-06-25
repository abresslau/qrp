"""52-week price extremes (Story 3.2-ext) — trailing high/low + how far off.

A new metric on the returns rails: the trailing **52-week (365 calendar days,
inclusive) high and low** of the adjusted close, the session each extreme was set,
and how far the current price sits off each (``pct_off_high`` ≤ 0, ``pct_off_low`` ≥ 0).

This is deliberately **not** a windowed return (ratio over a base→end pair), so it does
NOT live in ``fact_returns``/``return_window`` — it gets its own ``fact_price_extremes``
(equity) and ``fact_index_extremes`` (index) tables. But it is computed from the same
per-figi adjusted series the returns loader already holds in memory, so the loader runs
it in the same pass (no second price scan).

The extremum over the sliding window is computed in a single ascending pass with two
monotonic deques (the standard sliding-window-maximum/minimum algorithm) — O(sessions)
per security, never O(sessions × as_of_dates). On ties the **most recent** session that
achieved the extreme is recorded ("how long since it last printed the high").

Equity rows gate (AR-9): a row is held NULL when the as-of, the high date, or the low
date references an unreviewed ``prices_review`` flag. ``input_hash`` still reflects the
real endpoints so a later price revision re-dirties even a gated row (Story 3.6 dirty-set).
Index levels carry no gate, so the index path never gates.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

WINDOW_DAYS = 365  # trailing 52-week window, calendar days, inclusive of as_of_date


def extreme_input_hash(
    calendar_version: int | None,
    as_of_date: date,
    high: Decimal | None,
    high_date: date | None,
    low: Decimal | None,
    low_date: date | None,
    price: Decimal | None,
) -> str:
    """Stable hash of an extreme row's inputs (parity with returns ``input_hash``).

    Keyed on the calendar version (which fixes the trailing window's session set), the
    two extreme values and the dates they were set, **and the current price at the as-of
    session**. A price revision that moves the high or low changes the hash; the trailing
    ``price`` term additionally re-dirties the row when a same-day close is corrected
    *without* moving the trailing extreme (``pct_off_*`` depends on it, so the row would
    otherwise keep a stale pct-off — exactly the case ``fact_returns`` covers by hashing
    its endpoint prices). The dirty-set then rewrites the row even when it is gated.
    """
    payload = f"{calendar_version}|{as_of_date}|{high}|{high_date}|{low}|{low_date}|{price}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Extreme:
    """The trailing-window high and low and the sessions they were set."""

    high: Decimal
    high_date: date
    low: Decimal
    low_date: date


@dataclass(frozen=True)
class ExtremeRow:
    """One materialized 52-week extreme row (entity id added at upsert time)."""

    as_of_date: date
    high_52w: Decimal | None
    low_52w: Decimal | None
    high_52w_date: date | None
    low_52w_date: date | None
    pct_off_high: Decimal | None
    pct_off_low: Decimal | None
    input_hash: str
    gated: bool = False


def trailing_extremes(
    series: dict[date, Decimal],
    as_of_dates: Sequence[date],
    *,
    window_days: int = WINDOW_DAYS,
) -> dict[date, Extreme]:
    """Trailing high/low over ``[as_of − window_days, as_of]`` for each as-of (pure).

    ``series`` maps session date → price (adjusted close, or index level). ``as_of_dates``
    is iterated in ascending order; a shared right pointer admits every session ≤ the
    current as-of and the deque fronts are evicted once their date falls before the
    window's left edge. Two monotonic deques of indices give the max (decreasing) and min
    (increasing) in O(1) amortised per step. On ties the ``<=`` / ``>=`` back-pop collapses
    older equals so the front is the **most recent** session achieving the extreme.

    Only as-ofs with at least one session in the trailing window get an entry; an as-of
    with no priced session at/within the window (no history yet) is omitted. Securities
    with < 52 weeks of history use the extreme over whatever sessions exist (since
    inception within the window) — there is no partial-window flag.
    """
    sessions = sorted(series)
    if not sessions:
        return {}
    out: dict[date, Extreme] = {}
    max_dq: deque[int] = deque()  # indices, series values strictly decreasing front→back
    min_dq: deque[int] = deque()  # indices, series values strictly increasing front→back
    j = 0  # next session index to admit
    for as_of_date in sorted(as_of_dates):
        lo = as_of_date - timedelta(days=window_days)
        # Admit every session on/before as_of_date.
        while j < len(sessions) and sessions[j] <= as_of_date:
            val = series[sessions[j]]
            while max_dq and series[sessions[max_dq[-1]]] <= val:
                max_dq.pop()
            max_dq.append(j)
            while min_dq and series[sessions[min_dq[-1]]] >= val:
                min_dq.pop()
            min_dq.append(j)
            j += 1
        # Evict fronts that fell out of the trailing window's left edge.
        while max_dq and sessions[max_dq[0]] < lo:
            max_dq.popleft()
        while min_dq and sessions[min_dq[0]] < lo:
            min_dq.popleft()
        if not max_dq or not min_dq:
            continue  # no session within the window (e.g. as-of precedes all history)
        hi_i, lo_i = max_dq[0], min_dq[0]
        out[as_of_date] = Extreme(
            high=series[sessions[hi_i]], high_date=sessions[hi_i],
            low=series[sessions[lo_i]], low_date=sessions[lo_i],
        )
    return out


def compute_extreme_rows(
    series: dict[date, Decimal],
    as_of_dates: Sequence[date],
    calendar_version: int | None,
    *,
    gated_dates: Collection[date] = frozenset(),
    window_days: int = WINDOW_DAYS,
) -> list[ExtremeRow]:
    """52-week extreme rows for one entity across ``as_of_dates`` (pure).

    ``pct_off_high = price[as_of] / high − 1`` (≤ 0), ``pct_off_low = price[as_of] / low − 1``
    (≥ 0). A row is gated when the as-of, the high date, or the low date is an unreviewed
    flag (``gated_dates``); gated rows publish NULL values but the ``input_hash`` still
    reflects the real endpoints so a later price change (or review) re-dirties the row.
    """
    extremes = trailing_extremes(series, as_of_dates, window_days=window_days)
    rows: list[ExtremeRow] = []
    for as_of_date in as_of_dates:
        ext = extremes.get(as_of_date)
        if ext is None:
            continue
        gated = (
            as_of_date in gated_dates
            or ext.high_date in gated_dates
            or ext.low_date in gated_dates
        )
        price = series.get(as_of_date)
        pct_off_high = price / ext.high - 1 if price is not None and ext.high > 0 else None
        pct_off_low = price / ext.low - 1 if price is not None and ext.low > 0 else None
        ih = extreme_input_hash(
            calendar_version, as_of_date, ext.high, ext.high_date, ext.low, ext.low_date, price
        )
        rows.append(
            ExtremeRow(
                as_of_date=as_of_date,
                high_52w=None if gated else ext.high,
                low_52w=None if gated else ext.low,
                high_52w_date=None if gated else ext.high_date,
                low_52w_date=None if gated else ext.low_date,
                pct_off_high=None if gated else pct_off_high,
                pct_off_low=None if gated else pct_off_low,
                input_hash=ih,
                gated=gated,
            )
        )
    return rows
