"""Universe-member completeness contract (Story V1, the keystone).

A security that is a *current member of any universe* must have full **metadata**
(current name, current ticker symbology, MIC + currency, GICS), **prices**, and
**fundamentals** (shares outstanding). Any member missing any dimension is
persisted to ``universe_member_completeness`` with which dimensions are missing
and a severity:

* ``fail`` — a genuine omission we control (metadata missing; or priceable yet
  unpriced / no fundamentals);
* ``warn`` — an *expected* gap (delisted/suspended, or the MIC has no calendar →
  no vendor data is reachable);
* ``ok``   — complete.

The classification is pure; the sweep upserts a durable row per current member.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from sym.validate.results import CheckResult

# Ordered dimensions of "complete".
META_DIMS = ("name", "symbology", "gics")
MARKET_DIMS = ("prices", "fundamentals")
DIMENSIONS = META_DIMS + MARKET_DIMS

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class MemberFlags:
    """Presence flags + context for one current universe member."""

    has_name: bool
    has_symbology: bool
    has_gics: bool
    has_prices: bool
    has_fundamentals: bool
    status: str
    has_calendar: bool


@dataclass(frozen=True)
class Completeness:
    is_complete: bool
    missing: list[str]
    severity: str
    reason: str | None


def classify_member(flags: MemberFlags) -> Completeness:
    """Classify a member's completeness (pure).

    Missing metadata is always a ``fail`` (we can fill name/symbology from
    resolution and GICS from ``classify``). If only market data is missing, it is
    a ``warn`` when the security is delisted/suspended or its MIC has no calendar
    (no vendor data reachable), else a ``fail`` (priceable but not loaded).
    """
    present = {
        "name": flags.has_name,
        "symbology": flags.has_symbology,
        "gics": flags.has_gics,
        "prices": flags.has_prices,
        "fundamentals": flags.has_fundamentals,
    }
    missing = [d for d in DIMENSIONS if not present[d]]
    if not missing:
        return Completeness(True, [], OK, None)

    missing_meta = [d for d in missing if d in META_DIMS]
    if missing_meta:
        return Completeness(False, missing, FAIL, f"missing metadata: {', '.join(missing_meta)}")

    # Only market dimensions missing.
    if flags.status in ("delisted", "suspended"):
        return Completeness(
            False, missing, WARN, f"{flags.status}: {', '.join(missing)} unavailable"
        )
    if not flags.has_calendar:
        return Completeness(
            False, missing, WARN, f"no current calendar for MIC: {', '.join(missing)} unavailable"
        )
    return Completeness(False, missing, FAIL, f"priceable but missing: {', '.join(missing)}")


def _current_member_flags(
    conn: psycopg.Connection, universe_id: str | None = None
) -> list[tuple[str, str, MemberFlags]]:
    """Presence flags for every current member of every (or one) universe."""
    sql = """
        SELECT um.universe_id, um.composite_figi, s.status,
               EXISTS (SELECT 1 FROM security_names n
                        WHERE n.composite_figi = s.composite_figi AND n.valid_to IS NULL),
               EXISTS (SELECT 1 FROM security_symbology y
                        WHERE y.composite_figi = s.composite_figi
                          AND y.symbol_type = 'ticker' AND y.valid_to IS NULL),
               EXISTS (SELECT 1 FROM gics_scd g
                        WHERE g.composite_figi = s.composite_figi AND g.valid_to IS NULL),
               EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi),
               EXISTS (SELECT 1 FROM fundamentals f WHERE f.composite_figi = s.composite_figi),
               EXISTS (SELECT 1 FROM trading_calendar_version v
                        WHERE v.is_current AND v.mic = s.mic)
          FROM universe_membership um
          LEFT JOIN securities s USING (composite_figi)
         WHERE um.valid_to IS NULL
    """
    params: list[object] = []
    if universe_id is not None:
        sql += " AND um.universe_id = %s"
        params.append(universe_id)
    rows = conn.execute(sql, params).fetchall()
    out: list[tuple[str, str, MemberFlags | None]] = []
    for uid, figi, status, hn, hsy, hg, hp, hf, hc in rows:
        # LEFT JOIN (not INNER): a member with no securities master row must be
        # REPORTED as the worst incompleteness, not silently dropped from the check.
        flags = MemberFlags(hn, hsy, hg, hp, hf, status, hc) if status is not None else None
        out.append((uid, figi, flags))
    return out


def evaluate_completeness(
    conn: psycopg.Connection, universe_id: str | None = None
) -> CheckResult:
    """Assess + persist completeness for current universe members; return a result.

    Upserts one ``universe_member_completeness`` row per current member (durable
    log), and rolls up to a :class:`CheckResult` (fail = incomplete priceable /
    missing metadata; warn = expected gaps).
    """
    conn.autocommit = True
    if universe_id is not None:
        known = conn.execute(
            "SELECT 1 FROM universe WHERE universe_id = %s", (universe_id,)
        ).fetchone()
        if known is None:
            # A typo'd universe id must not yield a vacuous zero-member PASS.
            raise ValueError(f"unknown universe {universe_id!r}")
    members = _current_member_flags(conn, universe_id)
    # Purge log rows for ex-members in scope: upsert-only would report departed
    # members as incomplete forever.
    purge_sql = (
        "DELETE FROM universe_member_completeness c WHERE NOT EXISTS ("
        "SELECT 1 FROM universe_membership um WHERE um.universe_id = c.universe_id "
        "AND um.composite_figi = c.composite_figi AND um.valid_to IS NULL)"
    )
    purge_params: list[object] = []
    if universe_id is not None:
        purge_sql += " AND c.universe_id = %s"
        purge_params.append(universe_id)
    conn.execute(purge_sql, purge_params)
    failures: list[str] = []
    warnings: list[str] = []
    for uid, figi, flags in members:
        if flags is None:  # no securities master row — the worst gap there is
            failures.append(f"{uid}/{figi}: no securities master row")
            continue
        c = classify_member(flags)
        conn.execute(
            """
            INSERT INTO universe_member_completeness
                (universe_id, composite_figi, has_name, has_symbology, has_gics,
                 has_prices, has_fundamentals, is_complete, missing, severity, reason,
                 checked_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (universe_id, composite_figi) DO UPDATE
                SET has_name = EXCLUDED.has_name, has_symbology = EXCLUDED.has_symbology,
                    has_gics = EXCLUDED.has_gics, has_prices = EXCLUDED.has_prices,
                    has_fundamentals = EXCLUDED.has_fundamentals,
                    is_complete = EXCLUDED.is_complete, missing = EXCLUDED.missing,
                    severity = EXCLUDED.severity, reason = EXCLUDED.reason,
                    checked_at = EXCLUDED.checked_at
            """,
            (
                uid, figi, flags.has_name, flags.has_symbology, flags.has_gics,
                flags.has_prices, flags.has_fundamentals, c.is_complete,
                Jsonb(c.missing), c.severity, c.reason,
            ),
        )
        if c.severity == FAIL:
            failures.append(f"{uid}/{figi}: {c.reason}")
        elif c.severity == WARN:
            warnings.append(f"{uid}/{figi}: {c.reason}")
    detail = (
        f"{len(members)} current members; {len(failures)} incomplete (fail), "
        f"{len(warnings)} warn"
    )
    return CheckResult.from_items(
        "universe_member_completeness",
        checked=len(members),
        failures=failures,
        warnings=warnings,
        detail=detail,
    )


def incomplete_members(conn: psycopg.Connection, universe_id: str | None = None) -> list[dict]:
    """Logged incomplete members (for the review digest)."""
    sql = (
        "SELECT universe_id, composite_figi, missing, severity, reason "
        "FROM universe_member_completeness WHERE NOT is_complete"
    )
    params: list[object] = []
    if universe_id is not None:
        sql += " AND universe_id = %s"
        params.append(universe_id)
    sql += " ORDER BY severity DESC, universe_id, composite_figi"
    cols = ["universe_id", "composite_figi", "missing", "severity", "reason"]
    return [dict(zip(cols, r, strict=True)) for r in conn.execute(sql, params).fetchall()]


def completeness_summary(conn: psycopg.Connection) -> dict[str, int]:
    """Counts by severity across the completeness log (for review)."""
    rows = conn.execute(
        "SELECT severity, count(*) FROM universe_member_completeness GROUP BY severity"
    ).fetchall()
    return {sev: n for sev, n in rows}
