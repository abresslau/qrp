"""Link index universes to their reference index level series (B5).

An equity-index *universe* holds the point-in-time **constituents**
(`universe_membership`); the matching *index instrument* holds the published
**index level/return**. The `universe_benchmark` table links them (e.g. the sp500
universe ↔ the S&P 500 index series), so a study can pull both as-of any date.
This is a plain reference link — the index is NOT a portfolio benchmark; that role
is established per portfolio in the analytics layer. A universe can link to several
index instruments (price-return and total-return are distinct indices); one is the
primary. (The table keeps its historical name `universe_benchmark`; the concept is
"the universe's reference index".)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from sym.identity.instrument import SRC_YAHOO, sym_id_for
from sym.universe.query import members

# universe_id -> [(yahoo_symbol, role, is_primary)]. The yahoo symbol resolves to
# the index instrument's sym_id (loaded by `sym indices`).
UNIVERSE_INDICES: dict[str, list[tuple[str, str, bool]]] = {
    "sp500": [("^GSPC", "price_return", True), ("^SP500TR", "total_return", False)],
    "sp400": [("^MID", "price_return", True)],
    "sp600": [("^SP600", "price_return", True)],
    "dax": [("^GDAXI", "total_return", True)],
    "cac40": [("^FCHI", "price_return", True)],
    "ftse100": [("^FTSE", "price_return", True)],
    "ibex35": [("^IBEX", "price_return", True)],
    "ftsemib": [("FTSEMIB.MI", "price_return", True)],
    "aex": [("^AEX", "price_return", True)],
    "smi": [("^SSMI", "price_return", True)],
    "estoxx50": [("^STOXX50E", "price_return", True)],
}


@dataclass
class LinkSummary:
    linked: int = 0
    skipped_no_universe: int = 0
    skipped_no_instrument: int = 0


def link_universe_indices(conn: psycopg.Connection) -> LinkSummary:
    """Seed the `universe_benchmark` link table from the mapping (idempotent).

    Skips a mapping whose universe isn't defined or whose index instrument
    isn't loaded yet (run `sym indices` first to load the level series).
    """
    conn.autocommit = True
    summary = LinkSummary()
    for universe_id, links in UNIVERSE_INDICES.items():
        exists = conn.execute(
            "SELECT 1 FROM universe WHERE universe_id = %s", (universe_id,)
        ).fetchone()
        if exists is None:
            summary.skipped_no_universe += 1
            continue
        for yahoo_symbol, role, is_primary in links:
            sym_id = sym_id_for(conn, SRC_YAHOO, yahoo_symbol)
            if sym_id is None:
                summary.skipped_no_instrument += 1
                continue
            # DO UPDATE (not DO NOTHING): edits to a link's role or is_primary in
            # UNIVERSE_INDICES must converge into the map on the next run.
            inserted = conn.execute(
                """
                INSERT INTO universe_benchmark (universe_id, sym_id, role, is_primary)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (universe_id, sym_id) DO UPDATE
                    SET role = EXCLUDED.role, is_primary = EXCLUDED.is_primary
                RETURNING universe_id
                """,
                (universe_id, sym_id, role, is_primary),
            ).fetchone()
            if inserted is not None:
                summary.linked += 1
    return summary


def universe_indices(conn: psycopg.Connection, universe_id: str) -> list[dict]:
    """The index instruments linked to a universe (name + role + primary)."""
    rows = conn.execute(
        """
        SELECT b.sym_id, i.name, b.role, b.is_primary
          FROM universe_benchmark b JOIN instrument i USING (sym_id)
         WHERE b.universe_id = %s
         ORDER BY b.is_primary DESC, i.name
        """,
        (universe_id,),
    ).fetchall()
    return [
        {"sym_id": s, "name": n, "role": r, "is_primary": p} for s, n, r, p in rows
    ]


def primary_index(conn: psycopg.Connection, universe_id: str) -> int | None:
    """The primary index instrument's sym_id for a universe (or None)."""
    row = conn.execute(
        "SELECT sym_id FROM universe_benchmark WHERE universe_id = %s AND is_primary",
        (universe_id,),
    ).fetchone()
    return row[0] if row else None


@dataclass
class UniverseSnapshot:
    universe_id: str
    as_of_date: date
    members: set[str]
    index_sym_id: int | None
    index_level: object | None  # Decimal | None
    index_level_date: date | None = None  # the session the level was observed on


def universe_with_index(
    conn: psycopg.Connection, universe_id: str, as_of_date: date
) -> UniverseSnapshot:
    """Point-in-time constituents + the primary reference index's level, as-of a date.

    The payoff of the link: who was in the index *and* where the index closed on
    the same date. The carried-back level's own session is surfaced as
    ``index_level_date`` so a stale series is visible to the caller (the FX
    resolver's staleness-cap pattern, applied as transparency rather than a cutoff).
    (Index returns for any window are in `fact_index_returns`.)
    """
    member_figis = members(conn, universe_id, as_of_date)
    sym_id = primary_index(conn, universe_id)
    level = None
    level_date = None
    if sym_id is not None:
        row = conn.execute(
            "SELECT level, session_date FROM index_levels "
            "WHERE sym_id = %s AND session_date <= %s "
            "ORDER BY session_date DESC LIMIT 1",
            (sym_id, as_of_date),
        ).fetchone()
        if row:
            level, level_date = row
    return UniverseSnapshot(universe_id, as_of_date, member_figis, sym_id, level, level_date)
