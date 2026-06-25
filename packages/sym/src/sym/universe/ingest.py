"""Universe-driven ingestion (Epic U4) — the sym-side price-load bridge.

Drives price ingestion from *maintained universe membership* instead of a static seed: every
tracked, resolved member becomes a priceable security; a joiner's prior history is backfilled over
its membership window; a leaver stops forward fetches but keeps its history; and per-universe
coverage makes a partial load visible rather than hidden.

This module STAYS in sym (it loads into sym's ``prices_raw`` and writes the securities master).
Since membership moved to the ``universe`` package's own database, every function takes BOTH
connections: ``conn`` is the sym DB (securities / prices_raw / pipeline_backfill_progress) and
``u_conn`` is the universe DB (membership / resolutions). The cross-DB pattern is ROSTER-FETCH —
read the small member roster from the universe DB, then filter sym data by that ``composite_figi``
list (NO cross-DB join).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg
from equity.ingest.pipeline import OVERWRITE, LoadSummary, run_load
from universe.registry import InvalidMemberIdentifierError

from sym.identity.symbology import (
    ExchangeLookupError,
    SymbologyCollisionError,
    SymbologyTransitionError,
    write_security,
)
from sym.identity.universe import TICKER, SeedSecurity
from sym.universe.resolver import _parse_token


@dataclass
class BridgeSummary:
    created: int = 0
    existed: int = 0
    skipped_no_mic: int = 0
    skipped_no_exchange: int = 0
    skipped_bad_token: int = 0
    skipped_collision: int = 0  # recycled identifier / transition refusal (1.10)


def ensure_universe_securities(
    conn: psycopg.Connection, u_conn: psycopg.Connection, universe_id: str
) -> BridgeSummary:
    """Create `securities` rows for resolved members missing from the master.

    Roster-fetch: read the resolved members from the universe DB, find which are absent from sym's
    ``securities``, and reuse ``write_security`` for those. Idempotent.
    """
    conn.autocommit = True
    resolved = u_conn.execute(
        """
        SELECT raw_identifier, composite_figi, share_class_figi
          FROM universe_member_resolution
         WHERE universe_id = %s AND resolution_status = 'resolved'
        """,
        (universe_id,),
    ).fetchall()
    figis = [r[1] for r in resolved]
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT composite_figi FROM securities WHERE composite_figi = ANY(%s)", (figis,)
        ).fetchall()
    } if figis else set()
    summary = BridgeSummary()
    for raw, figi, share_class_figi in resolved:
        if figi in existing:
            summary.existed += 1
            continue
        try:
            symbol_type, value, mic = _parse_token(raw)
        except InvalidMemberIdentifierError:
            summary.skipped_bad_token += 1
            continue
        if symbol_type != TICKER or not mic:
            summary.skipped_no_mic += 1
            continue
        seed = SeedSecurity(raw, "universe_member", value, mic, None, None)
        try:
            with conn.transaction():
                created = write_security(
                    conn, seed=seed, composite_figi=figi, share_class_figi=share_class_figi
                )
        except ExchangeLookupError:
            summary.skipped_no_exchange += 1
            continue
        except (SymbologyCollisionError, SymbologyTransitionError):
            summary.skipped_collision += 1
            continue
        if created:
            summary.created += 1
        else:
            summary.existed += 1
    return summary


def universe_securities(
    conn: psycopg.Connection,
    u_conn: psycopg.Connection,
    eq_conn: psycopg.Connection,
    universe_id: str,
    as_of_date: date,
    *,
    backfill: bool,
) -> list[tuple[str, str, date | None, date, date | None]]:
    """The security set to ingest for a universe (roster-fetch, joined in Python).

    Returns ``(composite_figi, mic, cursor, member_from, member_to)`` per member that resolves AND
    exists in ``securities``. ``member_from`` = earliest membership ``valid_from`` (backfill floor);
    ``member_to`` = exit date (NULL if still a member — leaver fetch cap). A forward fill takes only
    members active as-of ``as_of_date``; a backfill/overwrite takes all (whole membership window).
    """
    # 1. membership roster from the universe DB (no securities join here).
    roster = u_conn.execute(
        """
        SELECT um.composite_figi,
               min(um.valid_from) AS member_from,
               CASE WHEN bool_or(um.valid_to IS NULL) THEN NULL
                    ELSE max(um.valid_to) END AS member_to,
               bool_or(um.valid_from <= %s AND (um.valid_to IS NULL OR um.valid_to > %s))
                   AS active_asof
          FROM universe_membership um
         WHERE um.universe_id = %s
         GROUP BY um.composite_figi
         ORDER BY um.composite_figi
        """,
        (as_of_date, as_of_date, universe_id),
    ).fetchall()
    figis = [r[0] for r in roster]
    if not figis:
        return []
    # 2. mic (only members that EXIST in securities — the original INNER JOIN) + backfill cursor,
    #    fetched from sym filtered by the roster list.
    mic_by_figi = {
        r[0]: (r[1].strip() if isinstance(r[1], str) else r[1])
        for r in conn.execute(
            "SELECT composite_figi, mic FROM securities WHERE composite_figi = ANY(%s)", (figis,)
        ).fetchall()
    }
    cursor_by_figi = dict(
        eq_conn.execute(
            "SELECT composite_figi, cursor_date FROM pipeline_backfill_progress "
            "WHERE composite_figi = ANY(%s)",
            (figis,),
        ).fetchall()
    )
    out: list[tuple[str, str, date | None, date, date | None]] = []
    for figi, member_from, member_to, active in roster:
        if figi not in mic_by_figi:  # not in the securities master → excluded (INNER JOIN parity)
            continue
        if not backfill and not active:
            continue  # forward modes skip leavers (stop forward fetch)
        out.append((figi, mic_by_figi[figi], cursor_by_figi.get(figi), member_from, member_to))
    return out


def run_universe_load(
    conn: psycopg.Connection,
    u_conn: psycopg.Connection,
    eq_conn: psycopg.Connection,
    source: object,
    universe_id: str,
    mode: str,
    *,
    as_of_date: date,
    ensure_securities: bool = True,
    history_floor: date | None = None,
    **kwargs: object,
) -> LoadSummary:
    """Load prices for a universe's members from maintained membership (cross-DB roster-fetch).

    Bridges resolved members into ``securities`` (so new names are priceable), then runs the
    standard pipeline over the membership selection with a per-figi backfill floor (joiner) and
    an end cap (leaver exit). ``conn`` is sym (securities); ``u_conn`` is the universe DB
    (membership); ``eq_conn`` is the equity DB (prices/returns the load writes into).
    """
    if ensure_securities:
        ensure_universe_securities(conn, u_conn, universe_id)
        # Map any newly-created securities onto the instrument/sym_id spine immediately. Idempotent.
        from sym.identity.instrument import backfill_equity_instruments

        backfill_equity_instruments(conn)
    gap_aware = bool(kwargs.get("gap_aware", False))
    select_all_members = gap_aware or mode == OVERWRITE
    selection = universe_securities(
        conn, u_conn, eq_conn, universe_id, as_of_date, backfill=select_all_members
    )
    securities = [(figi, mic, cursor) for figi, mic, cursor, _f, _t in selection]
    cap_map = {figi: member_to for figi, _m, _c, _f, member_to in selection}
    floor_for = None
    if history_floor is not None:
        def floor_for(_figi: str) -> date:  # noqa: F811
            return history_floor
    return run_load(
        eq_conn,
        conn,
        source,
        mode,
        as_of_date=as_of_date,
        securities=securities,
        floor_for=floor_for,
        end_cap_for=cap_map.get,
        **kwargs,  # type: ignore[arg-type]
    )


@dataclass
class Coverage:
    universe_id: str
    members_total: int = 0
    resolved: int = 0
    unresolved: int = 0
    in_master: int = 0
    priced: int = 0
    current_members: int = 0
    current_priced: int = 0

    @property
    def resolved_pct(self) -> float:
        return self.resolved / self.members_total if self.members_total else 0.0

    @property
    def priced_pct(self) -> float:
        """Priced as a fraction of resolved members (the reachable set)."""
        return self.priced / self.resolved if self.resolved else 0.0

    @property
    def current_priced_pct(self) -> float:
        return self.current_priced / self.current_members if self.current_members else 0.0


def coverage(
    conn: psycopg.Connection,
    u_conn: psycopg.Connection,
    eq_conn: psycopg.Connection,
    universe_id: str,
    as_of_date: date,
) -> Coverage:
    """Per-universe coverage so a partial load can't masquerade as complete (cross-DB)."""
    cov = Coverage(universe_id)
    res = dict(
        u_conn.execute(
            """
            SELECT resolution_status, count(*) FROM universe_member_resolution
             WHERE universe_id = %s GROUP BY resolution_status
            """,
            (universe_id,),
        ).fetchall()
    )
    cov.resolved = res.get("resolved", 0)
    cov.unresolved = res.get("unresolved", 0)
    cov.members_total = sum(res.values())
    # resolved-member rosters from the universe DB; existence/pricing checked against sym by list.
    resolved_figis = [
        r[0]
        for r in u_conn.execute(
            "SELECT DISTINCT composite_figi FROM universe_member_resolution "
            "WHERE universe_id = %s AND resolution_status = 'resolved' "
            "AND composite_figi IS NOT NULL",
            (universe_id,),
        ).fetchall()
    ]
    current_figis = [
        r[0]
        for r in u_conn.execute(
            "SELECT DISTINCT composite_figi FROM universe_membership "
            "WHERE universe_id = %s AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)",
            (universe_id, as_of_date, as_of_date),
        ).fetchall()
    ]
    cov.current_members = len(current_figis)
    if resolved_figis:
        cov.in_master = conn.execute(
            "SELECT count(*) FROM securities WHERE composite_figi = ANY(%s)", (resolved_figis,)
        ).fetchone()[0]
        cov.priced = eq_conn.execute(
            "SELECT count(DISTINCT composite_figi) FROM prices_raw WHERE composite_figi = ANY(%s)",
            (resolved_figis,),
        ).fetchone()[0]
    if current_figis:
        cov.current_priced = eq_conn.execute(
            "SELECT count(DISTINCT composite_figi) FROM prices_raw WHERE composite_figi = ANY(%s)",
            (current_figis,),
        ).fetchone()[0]
    return cov
