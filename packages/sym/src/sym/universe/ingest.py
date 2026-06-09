"""Universe-driven ingestion (Epic U4).

Drives price ingestion from *maintained universe membership* instead of a static
seed: every tracked, resolved member becomes a priceable security; a joiner's
prior history is backfilled over its membership window; a leaver stops forward
fetches but keeps its history (survivorship-safe, Story 3.7); and per-universe
coverage makes a partial load visible rather than hidden.

The bridge (`ensure_universe_securities`) creates `securities` rows for resolved
members not yet in the master (reusing the identity layer's `write_security`), so
the existing ingestion + returns + SM-6 machinery then runs unchanged (NFR9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from sym.identity.symbology import ExchangeLookupError, write_security
from sym.identity.universe import TICKER, SeedSecurity
from sym.ingest.pipeline import OVERWRITE, LoadSummary, run_load
from sym.universe.registry import InvalidMemberIdentifierError
from sym.universe.resolution import _parse_token


@dataclass
class BridgeSummary:
    created: int = 0
    existed: int = 0
    skipped_no_mic: int = 0
    skipped_no_exchange: int = 0
    skipped_bad_token: int = 0


def ensure_universe_securities(conn: psycopg.Connection, universe_id: str) -> BridgeSummary:
    """Create `securities` rows for resolved members missing from the master.

    Reconstructs a one-off `SeedSecurity` from each member's frozen
    ``(ticker, mic)`` token + CompositeFIGI and reuses ``write_security`` (currency
    and country come from the exchange table). A token without a usable MIC, or a
    MIC absent from the exchange reference, is skipped and counted (a coverage gap,
    not a crash). Idempotent: an already-present security is left untouched.
    """
    conn.autocommit = True
    rows = conn.execute(
        """
        SELECT r.raw_identifier, r.composite_figi, r.share_class_figi
          FROM universe_member_resolution r
         WHERE r.universe_id = %s AND r.resolution_status = 'resolved'
           AND NOT EXISTS (
               SELECT 1 FROM securities s WHERE s.composite_figi = r.composite_figi
           )
        """,
        (universe_id,),
    ).fetchall()
    summary = BridgeSummary()
    for raw, figi, share_class_figi in rows:
        try:
            symbol_type, value, mic = _parse_token(raw)
        except InvalidMemberIdentifierError:
            summary.skipped_bad_token += 1
            continue
        if symbol_type != TICKER or not mic:
            # An ISIN-only token has no listing MIC → can't derive currency/country.
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
        if created:
            summary.created += 1
        else:
            summary.existed += 1
    return summary


def universe_securities(
    conn: psycopg.Connection, universe_id: str, as_of_date: date, *, backfill: bool
) -> list[tuple[str, str, date | None, date, date | None]]:
    """The security set to ingest for a universe.

    Returns ``(composite_figi, mic, cursor, member_from, member_to)`` per member
    that resolves AND exists in ``securities``. ``member_from`` is the earliest
    membership ``valid_from`` (the backfill floor); ``member_to`` is the exit date
    (NULL if still a member — the leaver fetch cap). A forward fill takes only
    members active as-of ``as_of_date``; a gap-aware (backfill) fill or an overwrite
    takes all (so a name's whole membership window is filled, leavers capped at their exit).
    """
    rows = conn.execute(
        """
        SELECT um.composite_figi, s.mic, p.cursor_date,
               min(um.valid_from) AS member_from,
               CASE WHEN bool_or(um.valid_to IS NULL) THEN NULL
                    ELSE max(um.valid_to) END AS member_to,
               bool_or(um.valid_from <= %s AND (um.valid_to IS NULL OR um.valid_to > %s))
                   AS active_asof
          FROM universe_membership um
          JOIN securities s USING (composite_figi)
          LEFT JOIN pipeline_backfill_progress p ON p.composite_figi = um.composite_figi
         WHERE um.universe_id = %s
         GROUP BY um.composite_figi, s.mic, p.cursor_date
         ORDER BY um.composite_figi
        """,
        (as_of_date, as_of_date, universe_id),
    ).fetchall()
    out: list[tuple[str, str, date | None, date, date | None]] = []
    for figi, mic, cursor, member_from, member_to, active in rows:
        if not backfill and not active:
            continue  # forward modes skip leavers (stop forward fetch)
        out.append(
            (figi, mic.strip() if isinstance(mic, str) else mic, cursor, member_from, member_to)
        )
    return out


def run_universe_load(
    conn: psycopg.Connection,
    source: object,
    universe_id: str,
    mode: str,
    *,
    as_of_date: date,
    ensure_securities: bool = True,
    history_floor: date | None = None,
    **kwargs: object,
) -> LoadSummary:
    """Load prices for a universe's members from maintained membership.

    Bridges resolved members into ``securities`` (so new names are priceable), then
    runs the standard pipeline over the membership selection with a per-figi backfill
    floor (joiner window) and end cap (leaver exit).

    Price history is **factual and independent of the membership window**: backfill
    fetches each member's full available history (down to the pipeline's deep
    ``DEFAULT_FLOOR``, or ``history_floor`` if given) — the gap-aware backfill then
    fills any history below what is already stored, even for a name first loaded
    from its membership-join date. The membership PIT boundary (``pit_valid_from``)
    is unaffected — it governs *membership* queries, not price coverage. Leaver
    end-caps still apply (no point fetching past a delisted name's exit).
    """
    if ensure_securities:
        ensure_universe_securities(conn, universe_id)
        # Map any newly-created securities onto the instrument/sym_id spine immediately — this
        # is where securities are born, so it closes the bridge at the source (the nightly EOD
        # `map` step is the safety net). Idempotent. See docs/data-conventions.md §3.
        from sym.identity.instrument import backfill_equity_instruments

        backfill_equity_instruments(conn)
    # A forward fill follows current membership and skips leavers. History modes —
    # a gap-aware (backfill) fill, or an overwrite — must cover every point-in-time
    # member in the window, or a historical re-fetch silently leaves leavers' bars
    # untouched (survivorship gap, and invisible to `sym validate`, whose completeness
    # check only sees current members).
    gap_aware = bool(kwargs.get("gap_aware", False))
    select_all_members = gap_aware or mode == OVERWRITE
    selection = universe_securities(conn, universe_id, as_of_date, backfill=select_all_members)
    securities = [(figi, mic, cursor) for figi, mic, cursor, _f, _t in selection]
    cap_map = {figi: member_to for figi, _m, _c, _f, member_to in selection}
    floor_for = None
    if history_floor is not None:
        def floor_for(_figi: str) -> date:  # noqa: F811
            return history_floor
    return run_load(
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


def coverage(conn: psycopg.Connection, universe_id: str, as_of_date: date) -> Coverage:
    """Per-universe coverage so a partial load can't masquerade as complete."""
    cov = Coverage(universe_id)
    res = dict(
        conn.execute(
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
    cov.in_master = conn.execute(
        """
        SELECT count(DISTINCT r.composite_figi)
          FROM universe_member_resolution r JOIN securities s USING (composite_figi)
         WHERE r.universe_id = %s AND r.resolution_status = 'resolved'
        """,
        (universe_id,),
    ).fetchone()[0]
    cov.priced = conn.execute(
        """
        SELECT count(DISTINCT r.composite_figi)
          FROM universe_member_resolution r
         WHERE r.universe_id = %s AND r.resolution_status = 'resolved'
           AND EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = r.composite_figi)
        """,
        (universe_id,),
    ).fetchone()[0]
    cov.current_members = conn.execute(
        """
        SELECT count(DISTINCT composite_figi) FROM universe_membership
         WHERE universe_id = %s AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)
        """,
        (universe_id, as_of_date, as_of_date),
    ).fetchone()[0]
    cov.current_priced = conn.execute(
        """
        SELECT count(DISTINCT um.composite_figi) FROM universe_membership um
         WHERE um.universe_id = %s AND um.valid_from <= %s
           AND (um.valid_to IS NULL OR um.valid_to > %s)
           AND EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = um.composite_figi)
        """,
        (universe_id, as_of_date, as_of_date),
    ).fetchone()[0]
    return cov
