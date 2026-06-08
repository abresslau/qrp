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

from sym.returns.windows import WINDOWS, base_date, canonical_return, end_date, period_years


def index_return_rows(
    sym_id: int,
    levels: dict[date, Decimal],
    asofs: Sequence[date],
    sessions: Sequence[date],
) -> list[tuple[int, int, date, Decimal | None]]:
    """(sym_id, window_id, as_of, ret) for one index series (pure).

    ``ret`` is the level ratio over each window (annualized where the window is);
    insufficient history → None. ``sessions`` is the index's own level-date list.
    """
    rows: list[tuple[int, int, date, Decimal | None]] = []
    for asof in asofs:
        for w in WINDOWS:
            end = end_date(w, asof, sessions)
            base = base_date(w, asof, sessions)
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
            rows.append((sym_id, w.id, asof, ret))
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
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fact_index_returns (sym_id, window_id, as_of_date, ret)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (sym_id, window_id, as_of_date) DO UPDATE
                SET ret = EXCLUDED.ret
            """,
            rows,
        )


def recompute_index_returns(
    conn: psycopg.Connection, *, start: date, end: date
) -> IndexReturnsSummary:
    """Materialize benchmark index returns into ``fact_index_returns`` for [start, end]."""
    conn.autocommit = True
    summary = IndexReturnsSummary()
    for sym_id in _index_series(conn):
        levels = _levels(conn, sym_id)
        if not levels:
            continue
        sessions = sorted(levels)
        asofs = [d for d in sessions if start <= d <= end]
        if not asofs:
            continue
        rows = index_return_rows(sym_id, levels, asofs, sessions)
        _upsert(conn, rows)
        summary.series += 1
        summary.rows += len(rows)
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
