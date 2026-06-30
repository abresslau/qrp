"""Commodity trailing-window returns over the continuous front-month settle.

Mirrors equity ``fact_returns`` / index ``fact_index_returns``: a price return over each window in
``equity.returns.windows`` (cumulative ratio-1, or CAGR for annualized windows), from the ``settle``
series, into ``commodity.return_daily``. The commodity's own settle dates are its calendar.

IMPORTANT — RAW continuous front-month: the settle series carries roll discontinuities (stored raw,
never back-adjusted), so these returns INCLUDE roll-day jumps; they are NOT roll-adjusted. A
non-positive settle (e.g. negative WTI) makes the window return undefined (NULL) per the canonical
return rule. Roll-adjustment is a deliberate later follow-up.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg
from equity.returns.windows import WINDOWS, base_date, canonical_return, end_date, period_years

SERIES_TYPE = "continuous_front"


def commodity_return_rows(
    code: str,
    settles: dict[date, Decimal],
    as_of_dates: Sequence[date],
    sessions: Sequence[date],
) -> list[tuple[str, str, date, Decimal | None]]:
    """(commodity_code, window_code, as_of_date, ret) for one commodity series (pure).

    ``ret`` is the settle ratio over each window (annualized where the window is); insufficient
    history or a non-positive endpoint → None. ``sessions`` is the commodity's own settle-date list.
    """
    rows: list[tuple[str, str, date, Decimal | None]] = []
    for as_of_date in as_of_dates:
        for w in WINDOWS:
            end = end_date(w, as_of_date, sessions)
            base = base_date(w, as_of_date, sessions)
            s_end = settles.get(end) if end is not None else None
            s_base = settles.get(base) if base is not None else None
            years = (
                period_years(end, base)
                if (w.annualized and base is not None and end is not None)
                else None
            )
            ret = (
                canonical_return(s_end, s_base, annualized=w.annualized, years=years)
                if s_end is not None and s_base is not None
                else None
            )
            rows.append((code, w.code, as_of_date, ret))
    return rows


@dataclass
class CommodityReturnsSummary:
    series: int = 0  # commodities
    rows: int = 0


def _codes(conn: psycopg.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT commodity_code FROM commodity.price_daily "
            "WHERE series_type = %s ORDER BY commodity_code",
            (SERIES_TYPE,),
        ).fetchall()
    ]


def _settles(conn: psycopg.Connection, code: str) -> dict[date, Decimal]:
    rows = conn.execute(
        "SELECT as_of_date, settle FROM commodity.price_daily "
        "WHERE commodity_code = %s AND series_type = %s ORDER BY as_of_date",
        (code, SERIES_TYPE),
    ).fetchall()
    return {d: s for d, s in rows}


def _upsert(conn: psycopg.Connection, rows: Sequence[tuple]) -> None:
    if not rows:
        return
    # One transaction per series: under autocommit an interrupt mid-executemany would leave a
    # half-written series (self-healing, but visibly inconsistent). Mirrors recompute_index_returns.
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO commodity.return_daily
                (commodity_code, series_type, window_code, as_of_date, ret, computed_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (commodity_code, series_type, window_code, as_of_date) DO UPDATE
                SET ret = EXCLUDED.ret, computed_at = now()
            """,
            [(code, SERIES_TYPE, wc, d, ret) for (code, wc, d, ret) in rows],
        )


def recompute_commodity_returns(
    conn: psycopg.Connection, *, start_date: date, end_date: date
) -> CommodityReturnsSummary:
    """Materialise commodity trailing-window returns into ``commodity.return_daily`` for
    [start_date, end_date]. Idempotent (UPSERT). Per-commodity transaction."""
    conn.autocommit = True
    summary = CommodityReturnsSummary()
    for code in _codes(conn):
        settles = _settles(conn, code)
        if not settles:
            continue
        sessions = sorted(settles)
        as_of_dates = [d for d in sessions if start_date <= d <= end_date]
        if not as_of_dates:
            continue
        rows = commodity_return_rows(code, settles, as_of_dates, sessions)
        _upsert(conn, rows)
        summary.series += 1
        summary.rows += len(rows)
    return summary
