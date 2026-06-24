"""sym-side identity resolver adapter for the `universe` package (one-way ``sym → universe``).

`universe` defines the ``Resolver`` protocol (token→CompositeFIGI + a trading-calendar lookup) and
imports nothing from sym. This module is sym's implementation: it reuses the identity layer's
OpenFIGI resolver (``identity/figi.plan_resolutions``) and the local securities-master rescue, and
exposes the trading-calendar session lookup the universe monitor needs. ``SymResolver`` is what
sym's CLI / EOD / refresh paths inject into ``universe.monitor.run_monitor`` /
``universe.refresh.refresh_universe`` / ``universe.resolve_universe_members``.

This is the resolver IMPLEMENTATION that used to live in ``sym.universe.resolution`` before the
membership domain moved to the ``universe`` package.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import date

import psycopg
from universe.registry import (
    CRITERIA,
    CUSTOM_LIST,
    RESOLVED,
    UNRESOLVED,
    InvalidMemberIdentifierError,
)
from universe.resolution import FIGI, TICKER, MemberResolution, ResolveFn, _parse_token

from sym.identity.figi import ASSIGNED, plan_resolutions, read_exch_codes
from sym.identity.universe import SeedSecurity

# ``_parse_token`` / ``FIGI`` / ``TICKER`` are re-exported from universe.resolution (the pure
# member-token vocabulary lives in the universe package); imported here so existing callers of
# ``sym.universe.resolver._parse_token`` (ingest.py, tests) keep working.

__all__ = [
    "FIGI", "_parse_token", "SymResolver",
    "make_local_resolve_fn", "make_openfigi_resolve_fn",
]


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
    out: dict[str, MemberResolution] = {}
    parseable: list[str] = []
    for rid in raw_identifiers:
        try:
            _parse_token(rid)
            parseable.append(rid)
        except InvalidMemberIdentifierError as exc:
            out[rid] = MemberResolution(rid, None, None, UNRESOLVED, str(exc)[:200])
    seeds = [_seed_from_identifier(rid) for rid in parseable]
    resolutions = plan_resolutions(seeds, client, exch_codes)  # type: ignore[arg-type]
    out.update(
        {
            rid: _to_member_resolution(rid, res)
            for rid, res in zip(parseable, resolutions, strict=True)
        }
    )
    return out


def make_openfigi_resolve_fn(conn: psycopg.Connection, client: object) -> ResolveFn:
    """A resolver that maps member tokens via OpenFIGI (for new names, e.g. U2 indices).

    OpenFIGI misses fall through to a local-master rescue pass (a departed member is usually already
    in the master; without the rescue a mis-MIC'd leave row freezes unresolved and never leaves).
    """
    exch_codes = read_exch_codes(conn)
    local = make_local_resolve_fn(conn)

    def resolve(raw_identifiers: Sequence[str]) -> dict[str, MemberResolution]:
        out = resolve_identifiers(client, exch_codes, list(raw_identifiers))
        misses = [rid for rid, mr in out.items() if mr.resolution_status == UNRESOLVED]
        if misses:
            for rid, mr in local(misses).items():
                if mr.resolution_status == RESOLVED:
                    out[rid] = MemberResolution(
                        rid, mr.composite_figi, mr.share_class_figi, RESOLVED,
                        "local-master fallback (OpenFIGI miss)",
                    )
        return out

    return resolve


def make_local_resolve_fn(conn: psycopg.Connection) -> ResolveFn:
    """A resolver that maps member tokens against EXISTING securities (no network)."""

    def resolve(raw_identifiers: Sequence[str]) -> dict[str, MemberResolution]:
        out: dict[str, MemberResolution] = {}
        for rid in raw_identifiers:
            try:
                symbol_type, value, mic = _parse_token(rid)
            except InvalidMemberIdentifierError as exc:
                out[rid] = MemberResolution(rid, None, None, UNRESOLVED, str(exc)[:200])
                continue
            if symbol_type == FIGI:
                row = conn.execute(
                    "SELECT composite_figi, share_class_figi FROM securities "
                    "WHERE composite_figi = %s",
                    (value,),
                ).fetchone()
            else:
                candidates = [value, value.replace(".", "/")] if "." in value else [value]
                row = None
                if mic is not None:
                    row = conn.execute(
                        """
                        SELECT s.composite_figi, s.share_class_figi
                          FROM security_symbology y
                          JOIN securities s USING (composite_figi)
                         WHERE y.symbol_type = %s AND y.symbol_value = ANY(%s)
                           AND y.valid_to IS NULL AND s.mic = %s
                         ORDER BY s.composite_figi LIMIT 1
                        """,
                        (symbol_type, candidates, mic),
                    ).fetchone()
                if row is None:
                    row = conn.execute(
                        """
                        SELECT s.composite_figi, s.share_class_figi
                          FROM security_symbology y
                          JOIN securities s USING (composite_figi)
                         WHERE y.symbol_type = %s AND y.symbol_value = ANY(%s)
                           AND y.valid_to IS NULL
                         ORDER BY s.composite_figi LIMIT 1
                        """,
                        (symbol_type, candidates),
                    ).fetchone()
            if row is not None:
                out[rid] = MemberResolution(rid, row[0], row[1], RESOLVED)
            else:
                out[rid] = MemberResolution(
                    rid, None, None, UNRESOLVED, "not found in securities master"
                )
        return out

    return resolve


class SymResolver:
    """sym's implementation of ``universe.Resolver`` (identity resolution + calendar lookup).

    Holds the sym connection (and an optional OpenFIGI client). Inject one instance into the
    universe monitor / refresh / resolution entry points — they call ``resolve_fn(kind)`` and
    ``calendar_session(mic, d)`` without importing sym.
    """

    def __init__(self, conn: psycopg.Connection, client: object | None = None) -> None:
        self._conn = conn
        self._client = client

    def resolve_fn(self, kind: str) -> ResolveFn:
        if kind in (CUSTOM_LIST, CRITERIA):
            return make_local_resolve_fn(self._conn)
        client = self._client
        if client is None:
            from sym.identity.figi import HttpOpenFigiClient

            client = HttpOpenFigiClient(api_key=os.environ.get("OPENFIGI_API_KEY"), max_retries=6)
        return make_openfigi_resolve_fn(self._conn, client)

    def local_resolve_fn(self) -> ResolveFn:
        return make_local_resolve_fn(self._conn)

    def calendar_session(self, mic: str, on_or_before: date) -> date | None:
        row = self._conn.execute(
            """
            SELECT max(tc.session_date)
              FROM trading_calendar tc
              JOIN trading_calendar_version v USING (calendar_version)
             WHERE v.is_current AND tc.mic = %s AND tc.session_date <= %s
            """,
            (mic, on_or_before),
        ).fetchone()
        return row[0] if row else None
