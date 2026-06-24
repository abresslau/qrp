"""Membership resolution — universe-side orchestration + the injected Resolver seam (Story U1.3).

A universe member's ``raw_identifier`` token is resolved to a CompositeFIGI ONCE and frozen by the
``(universe_id, raw_identifier)`` PK (a recycled ticker can't re-point a historical member);
unresolvable members are RETAINED with status ``unresolved`` (survivorship). The actual token→FIGI
resolution and the securities-master writes live in the **identity layer (sym)** — universe must not
import sym, so it defines the ``Resolver`` protocol here and sym injects an implementation. The
dependency edge is one-way ``sym → universe``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import psycopg

from universe.registry import RESOLVED, UNRESOLVED, InvalidMemberIdentifierError

# A resolver strategy: raw_identifiers -> {raw_identifier: MemberResolution}.
ResolveFn = Callable[[Sequence[str]], dict[str, "MemberResolution"]]

# Member-token vocabulary (pure; the values match sym's security_symbology.symbol_type strings).
TICKER = "ticker"
ISIN = "isin"
FIGI = "figi"
_TICKER_PREFIX = "ticker:"
_ISIN_PREFIX = "isin:"
_FIGI_PREFIX = "figi:"


def _parse_token(raw_identifier: str) -> tuple[str, str, str | None]:
    """Parse a member token into ``(symbol_type, value, mic|None)`` (pure).

    ``ticker:AAPL@XNAS`` -> ``('ticker', 'AAPL', 'XNAS')``; ``isin:US0378331005`` ->
    ``('isin', 'US0378331005', None)``; ``figi:BBG…`` -> ``('figi', 'BBG…', None)``.
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


class Resolver(Protocol):
    """The sym-side bridge universe needs, injected so universe imports nothing from sym.

    Bundles the two things the membership domain requires from sym: identity resolution
    (token→CompositeFIGI, reading the securities master / OpenFIGI) and the trading-calendar
    lookup used to snap monitor-discovered changes to sessions. sym provides the implementation
    (``sym.universe.resolver.SymResolver``); one-way ``sym → universe``.
    """

    def resolve_fn(self, kind: str) -> ResolveFn:
        """The resolve strategy for a universe of this ``kind`` (local-master vs OpenFIGI)."""
        ...

    def local_resolve_fn(self) -> ResolveFn:
        """The no-network local-master resolver (used by the accuracy gate's FIGI fallback)."""
        ...

    def calendar_session(self, mic: str, on_or_before: date) -> date | None:
        """Latest trading session on/before ``on_or_before`` for ``mic`` (None if unknown)."""
        ...


def _unresolved_identifiers(
    conn: psycopg.Connection, universe_id: str, *, retry_unresolved: bool = False
) -> list[str]:
    """Distinct member ids in the universe's event log not yet resolved (frozen).

    With ``retry_unresolved``, members frozen as ``unresolved`` are included too — a transient
    OpenFIGI outage must not leave a member unresolvable forever. RESOLVED outcomes are never
    revisited (frozen by design).
    """
    rows = conn.execute(
        """
        SELECT DISTINCT e.raw_identifier
          FROM membership_event e
          LEFT JOIN universe_member_resolution r
            ON r.universe_id = e.universe_id AND r.raw_identifier = e.raw_identifier
         WHERE e.universe_id = %s
           AND (r.raw_identifier IS NULL OR (%s AND r.resolution_status = %s))
         ORDER BY e.raw_identifier
        """,
        (universe_id, retry_unresolved, UNRESOLVED),
    ).fetchall()
    return [r[0] for r in rows]


def resolve_universe_members(
    conn: psycopg.Connection,
    universe_id: str,
    resolve_fn: ResolveFn,
    *,
    chunk_size: int = 100,
    retry_unresolved: bool = False,
) -> ResolutionSummary:
    """Resolve a universe's not-yet-resolved members and freeze the outcomes.

    ``conn`` is the universe DB (membership_event + universe_member_resolution); ``resolve_fn`` is
    the injected strategy (built by the sym resolver — it closes over the sym connection / OpenFIGI
    client). Members with a frozen RESOLVED outcome are never re-pointed (a recycled ticker can't
    corrupt a historical member). ``retry_unresolved`` additionally re-attempts members frozen
    ``unresolved`` (upgrade-only): pass it from explicit refreshes, not the daily monitor (bounds
    OpenFIGI quota spend). Runs in ``chunk_size`` batches; with an autocommit connection each chunk
    is durable before the next, so a long live run is resumable.
    """
    summary = ResolutionSummary()
    pending = _unresolved_identifiers(conn, universe_id, retry_unresolved=retry_unresolved)
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
        # Upgrade-only upsert: a fresh outcome replaces an UNRESOLVED row only when it actually
        # resolved; a frozen RESOLVED row is never touched. The upgrade re-stamps resolved_at — the
        # column means "when this mapping LAST became visible" (insert or upgrade) — which keeps the
        # snapshot-pin resolution watermark sound (U1.7). A resolved->'unpriced' status flip must
        # NOT re-stamp resolved_at (the figi mapping is unchanged).
        inserted = conn.execute(
            """
            INSERT INTO universe_member_resolution
                (universe_id, raw_identifier, composite_figi, share_class_figi,
                 resolution_status, detail)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (universe_id, raw_identifier) DO UPDATE
                SET composite_figi = EXCLUDED.composite_figi,
                    share_class_figi = EXCLUDED.share_class_figi,
                    resolution_status = EXCLUDED.resolution_status,
                    detail = EXCLUDED.detail,
                    resolved_at = now()
                WHERE universe_member_resolution.resolution_status = %s
                  AND EXCLUDED.resolution_status = %s
            RETURNING raw_identifier
            """,
            (universe_id, raw, mr.composite_figi, mr.share_class_figi,
             mr.resolution_status, mr.detail, UNRESOLVED, RESOLVED),
        ).fetchone()
        if inserted is None:
            continue
        summary.written += 1
        if mr.resolution_status == RESOLVED:
            summary.resolved += 1
        else:
            summary.unresolved += 1
