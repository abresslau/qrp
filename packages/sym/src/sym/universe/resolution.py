"""Membership resolution bridge (Story U1.3).

Resolves a universe member's ``raw_identifier`` token (``ticker:T@MIC`` |
``isin:XXX``) to a CompositeFIGI by reusing the identity layer's OpenFIGI
resolver (``identity/figi.plan_resolutions`` — ISIN-first/fallback + home-listing
narrowing + share-class-conflict detection). Resolution is **frozen**: written
once per ``(universe_id, raw_identifier)`` and never re-pointed (so a recycled
ticker can't corrupt a historical member). Unresolvable members are **retained**
with status ``unresolved`` — never dropped (survivorship).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import psycopg

from sym.identity.figi import ASSIGNED, plan_resolutions, read_exch_codes
from sym.identity.universe import ISIN, TICKER, SeedSecurity
from sym.universe.registry import (
    RESOLVED,
    UNRESOLVED,
    InvalidMemberIdentifierError,
)

# A resolver strategy: raw_identifiers -> {raw_identifier: MemberResolution}.
ResolveFn = Callable[[Sequence[str]], dict[str, "MemberResolution"]]

_TICKER_PREFIX = "ticker:"
_ISIN_PREFIX = "isin:"
_FIGI_PREFIX = "figi:"
FIGI = "figi"


@dataclass(frozen=True)
class MemberResolution:
    raw_identifier: str
    composite_figi: str | None
    share_class_figi: str | None
    resolution_status: str
    detail: str | None = None


@dataclass
class ResolutionSummary:
    written: int = 0
    resolved: int = 0
    unresolved: int = 0


def _parse_token(raw_identifier: str) -> tuple[str, str, str | None]:
    """Parse a member token into ``(symbol_type, value, mic|None)``.

    ``ticker:AAPL@XNAS`` -> ``('ticker', 'AAPL', 'XNAS')``; ``isin:US0378331005``
    -> ``('isin', 'US0378331005', None)``.
    """
    if raw_identifier.startswith(_TICKER_PREFIX):
        ticker, sep, mic = raw_identifier[len(_TICKER_PREFIX):].partition("@")
        if not sep or not ticker or not mic:
            raise InvalidMemberIdentifierError(
                f"{raw_identifier!r}: ticker token must be 'ticker:<TICKER>@<MIC>'"
            )
        return TICKER, ticker, mic
    if raw_identifier.startswith(_ISIN_PREFIX):
        isin = raw_identifier[len(_ISIN_PREFIX):]
        if not isin:
            raise InvalidMemberIdentifierError(f"{raw_identifier!r}: empty isin token")
        return ISIN, isin, None
    if raw_identifier.startswith(_FIGI_PREFIX):
        figi = raw_identifier[len(_FIGI_PREFIX):]
        if not figi:
            raise InvalidMemberIdentifierError(f"{raw_identifier!r}: empty figi token")
        return FIGI, figi, None
    raise InvalidMemberIdentifierError(
        f"{raw_identifier!r}: expected a 'ticker:T@MIC', 'isin:XXX', or 'figi:XXX' token"
    )


def _seed_from_identifier(raw_identifier: str) -> SeedSecurity:
    """Parse a member token into a one-off SeedSecurity for the OpenFIGI resolver."""
    symbol_type, value, mic = _parse_token(raw_identifier)
    if symbol_type == TICKER:
        return SeedSecurity(raw_identifier, "universe_member", value, mic, None, None)
    return SeedSecurity(raw_identifier, "universe_member", None, None, value, None)


def _to_member_resolution(raw_identifier: str, resolution: object) -> MemberResolution:
    """Map an identity-layer Resolution onto a MemberResolution (retain-and-flag)."""
    if resolution.outcome == ASSIGNED:  # type: ignore[attr-defined]
        return MemberResolution(
            raw_identifier,
            resolution.composite_figi,  # type: ignore[attr-defined]
            resolution.share_class_figi,  # type: ignore[attr-defined]
            RESOLVED,
        )
    # NO_FIGI_FOUND / AMBIGUOUS_FIGI / SHARE_CLASS_CONFLICT -> retained, flagged.
    return MemberResolution(
        raw_identifier, None, None, UNRESOLVED,
        f"{resolution.outcome}: {resolution.detail}",  # type: ignore[attr-defined]
    )


def resolve_identifiers(
    client: object, exch_codes: dict[str, str], raw_identifiers: list[str]
) -> dict[str, MemberResolution]:
    """Resolve member tokens to outcomes (pure — reuses ``plan_resolutions``)."""
    if not raw_identifiers:
        return {}
    seeds = [_seed_from_identifier(rid) for rid in raw_identifiers]
    resolutions = plan_resolutions(seeds, client, exch_codes)  # type: ignore[arg-type]
    return {
        rid: _to_member_resolution(rid, res)
        for rid, res in zip(raw_identifiers, resolutions, strict=True)
    }


def make_openfigi_resolve_fn(conn: psycopg.Connection, client: object) -> ResolveFn:
    """A resolver that maps member tokens via OpenFIGI (for new names, e.g. U2 indexes)."""
    exch_codes = read_exch_codes(conn)
    return lambda raw_identifiers: resolve_identifiers(client, exch_codes, list(raw_identifiers))


def make_local_resolve_fn(conn: psycopg.Connection) -> ResolveFn:
    """A resolver that maps member tokens against EXISTING securities (no network).

    Reuses the already-resolved `security_symbology` (Story 1.6): a member whose
    current ticker/isin is in the master resolves to its CompositeFIGI; one that
    isn't (e.g. a never-resolved delisting) is retained as ``unresolved``.
    """

    def resolve(raw_identifiers: Sequence[str]) -> dict[str, MemberResolution]:
        out: dict[str, MemberResolution] = {}
        for rid in raw_identifiers:
            symbol_type, value, _mic = _parse_token(rid)
            if symbol_type == FIGI:
                # A figi token (criteria screens, U5) resolves directly to itself.
                row = conn.execute(
                    "SELECT composite_figi, share_class_figi FROM securities "
                    "WHERE composite_figi = %s",
                    (value,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT s.composite_figi, s.share_class_figi
                      FROM security_symbology y
                      JOIN securities s USING (composite_figi)
                     WHERE y.symbol_type = %s AND y.symbol_value = %s AND y.valid_to IS NULL
                     LIMIT 1
                    """,
                    (symbol_type, value),
                ).fetchone()
            if row is not None:
                out[rid] = MemberResolution(rid, row[0], row[1], RESOLVED)
            else:
                out[rid] = MemberResolution(
                    rid, None, None, UNRESOLVED, "not found in securities master"
                )
        return out

    return resolve


def _unresolved_identifiers(conn: psycopg.Connection, universe_id: str) -> list[str]:
    """Distinct member ids in the universe's event log not yet resolved (frozen)."""
    rows = conn.execute(
        """
        SELECT DISTINCT e.raw_identifier
          FROM membership_event e
         WHERE e.universe_id = %s
           AND NOT EXISTS (
               SELECT 1 FROM universe_member_resolution r
                WHERE r.universe_id = e.universe_id AND r.raw_identifier = e.raw_identifier
           )
         ORDER BY e.raw_identifier
        """,
        (universe_id,),
    ).fetchall()
    return [r[0] for r in rows]


def resolve_universe_members(
    conn: psycopg.Connection, universe_id: str, resolve_fn: ResolveFn, *, chunk_size: int = 100
) -> ResolutionSummary:
    """Resolve a universe's not-yet-resolved members and freeze the outcomes.

    ``resolve_fn`` is the strategy (``make_local_resolve_fn`` for known securities,
    ``make_openfigi_resolve_fn`` for new names). Only members absent from
    ``universe_member_resolution`` are resolved, so a re-run is cheap and never
    re-points an already-frozen member (AC #2/#4).

    Resolution runs in ``chunk_size`` batches; with an autocommit connection each
    chunk's writes are durable before the next is fetched, so a long live run
    (hundreds of OpenFIGI lookups) is **resumable** — a re-run picks up exactly the
    members still missing a frozen resolution.
    """
    summary = ResolutionSummary()
    pending = _unresolved_identifiers(conn, universe_id)
    if not pending:
        return summary
    for start in range(0, len(pending), chunk_size):
        chunk = pending[start : start + chunk_size]
        _write_resolutions(conn, universe_id, resolve_fn(chunk), summary)
    return summary


def _write_resolutions(
    conn: psycopg.Connection,
    universe_id: str,
    resolutions: dict[str, MemberResolution],
    summary: ResolutionSummary,
) -> None:
    for raw, mr in resolutions.items():
        inserted = conn.execute(
            """
            INSERT INTO universe_member_resolution
                (universe_id, raw_identifier, composite_figi, share_class_figi,
                 resolution_status, detail)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (universe_id, raw_identifier) DO NOTHING
            RETURNING raw_identifier
            """,
            (universe_id, raw, mr.composite_figi, mr.share_class_figi,
             mr.resolution_status, mr.detail),
        ).fetchone()
        if inserted is None:
            continue
        summary.written += 1
        if mr.resolution_status == RESOLVED:
            summary.resolved += 1
        else:
            summary.unresolved += 1
