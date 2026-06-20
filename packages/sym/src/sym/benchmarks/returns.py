"""Benchmark index returns + alpha (Benchmark epic, B3).

Index returns are pure **level ratios** over the same windows as `fact_returns`
(reusing `returns.windows`) — no split/dividend math, since an index level already
embeds its return treatment via its variant. The index's own level dates serve as
its session calendar. Alpha is the excess return: an asset/universe return minus
the benchmark return at the same window + as_of_date.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from sym.returns.extremes import compute_extreme_rows
from sym.returns.windows import WINDOWS, base_date, canonical_return, end_date, period_years


def index_return_rows(
    sym_id: int,
    levels: dict[date, Decimal],
    as_of_dates: Sequence[date],
    sessions: Sequence[date],
) -> list[tuple[int, int, date, Decimal | None]]:
    """(sym_id, window_id, as_of_date, ret) for one index series (pure).

    ``ret`` is the level ratio over each window (annualized where the window is);
    insufficient history → None. ``sessions`` is the index's own level-date list.
    """
    rows: list[tuple[int, int, date, Decimal | None]] = []
    for as_of_date in as_of_dates:
        for w in WINDOWS:
            end = end_date(w, as_of_date, sessions)
            base = base_date(w, as_of_date, sessions)
            lvl_end = levels.get(end) if end is not None else None
            lvl_base = levels.get(base) if base is not None else None
            years = (
                period_years(end, base)
                if (w.annualized and base is not None and end is not None)
                else None
            )
            ret = (
                canonical_return(lvl_end, lvl_base, annualized=w.annualized, years=years)
                if lvl_end is not None and lvl_base is not None
                else None
            )
            rows.append((sym_id, w.id, as_of_date, ret))
    return rows


def alpha(asset_return: Decimal | None, benchmark_return: Decimal | None) -> Decimal | None:
    """Excess return: asset − benchmark (None if either is missing)."""
    if asset_return is None or benchmark_return is None:
        return None
    return asset_return - benchmark_return


@dataclass
class IndexReturnsSummary:
    series: int = 0  # index instruments (sym_id)
    rows: int = 0
    extreme_rows: int = 0


def _index_series(conn: psycopg.Connection) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT sym_id FROM index_levels ORDER BY sym_id"
        ).fetchall()
    ]


def _levels(conn: psycopg.Connection, sym_id: int) -> dict[date, Decimal]:
    rows = conn.execute(
        "SELECT session_date, level FROM index_levels WHERE sym_id = %s ORDER BY session_date",
        (sym_id,),
    ).fetchall()
    return {d: lvl for d, lvl in rows}


def _upsert(conn: psycopg.Connection, rows: Sequence[tuple]) -> None:
    if not rows:
        return
    # One transaction per series: under autocommit an interrupt mid-executemany would
    # otherwise leave a half-written series (self-healing, but visibly inconsistent).
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fact_index_returns (sym_id, window_id, as_of_date, ret)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (sym_id, window_id, as_of_date) DO UPDATE
                SET ret = EXCLUDED.ret
            """,
            rows,
        )


def _upsert_extremes(conn: psycopg.Connection, sym_id: int, rows: Sequence) -> None:
    """UPSERT index 52-week extremes (Story 3.2-ext) — one txn per series, no gate."""
    if not rows:
        return
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fact_index_extremes
                (sym_id, as_of_date, high_52w, low_52w, high_52w_date, low_52w_date,
                 pct_off_high, pct_off_low, input_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sym_id, as_of_date) DO UPDATE
                SET high_52w = EXCLUDED.high_52w, low_52w = EXCLUDED.low_52w,
                    high_52w_date = EXCLUDED.high_52w_date,
                    low_52w_date = EXCLUDED.low_52w_date,
                    pct_off_high = EXCLUDED.pct_off_high, pct_off_low = EXCLUDED.pct_off_low,
                    input_hash = EXCLUDED.input_hash
                WHERE fact_index_extremes.input_hash IS DISTINCT FROM EXCLUDED.input_hash
            """,
            [
                (sym_id, r.as_of_date, r.high_52w, r.low_52w, r.high_52w_date,
                 r.low_52w_date, r.pct_off_high, r.pct_off_low, r.input_hash)
                for r in rows
            ],
        )


def recompute_index_returns(
    conn: psycopg.Connection, *, start_date: date, end_date: date
) -> IndexReturnsSummary:
    """Materialize benchmark index returns into ``fact_index_returns`` for [start_date, end_date].

    The same per-series pass also materializes the index 52-week extremes (Story 3.2-ext)
    into ``fact_index_extremes`` from the level series (no gate — index levels are unflagged).
    """
    conn.autocommit = True
    summary = IndexReturnsSummary()
    for sym_id in _index_series(conn):
        levels = _levels(conn, sym_id)
        if not levels:
            continue
        sessions = sorted(levels)
        as_of_dates = [d for d in sessions if start_date <= d <= end_date]
        if not as_of_dates:
            continue
        rows = index_return_rows(sym_id, levels, as_of_dates, sessions)
        _upsert(conn, rows)
        # current_calendar_version is figi/MIC-scoped and indexes use their own level
        # dates as the session set, so the extreme hash is keyed on None (no exchange
        # calendar) — the (sym_id, as_of_date, levels) inputs still re-dirty on a revision.
        extreme_rows = compute_extreme_rows(levels, as_of_dates, None)
        _upsert_extremes(conn, sym_id, extreme_rows)
        summary.series += 1
        summary.rows += len(rows)
        summary.extreme_rows += len(extreme_rows)
    return summary


def benchmark_return(
    conn: psycopg.Connection, sym_id: int, window_id: int, as_of_date: date
) -> Decimal | None:
    """The materialized benchmark return for one (sym_id, window, date)."""
    row = conn.execute(
        "SELECT ret FROM fact_index_returns "
        "WHERE sym_id = %s AND window_id = %s AND as_of_date = %s",
        (sym_id, window_id, as_of_date),
    ).fetchone()
    return row[0] if row else None
