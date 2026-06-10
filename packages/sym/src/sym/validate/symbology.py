"""Symbology & name completeness/uniqueness (Story V3).

Identity must be complete and unambiguous: every active security needs a current
ticker symbology and exactly one current name, and no
``(symbol_type, symbol_value, mic)`` may map to more than one current
``composite_figi`` (a true collision). Cross-exchange same-ticker (different MIC)
is *not* a collision — the MIC is part of the key — so LVMH ``MC@XPAR`` and Moelis
``MC@XNYS`` coexist cleanly. Pure detectors; live anti-join/group-by sweep.
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from sym.validate.results import CheckResult


def find_missing(required: set[str], present: set[str]) -> set[str]:
    """Members of ``required`` absent from ``present`` (pure)."""
    return required - present


def find_collisions(
    rows: Sequence[tuple[str, str, str | None, str]],
) -> dict[tuple[str, str, str | None], set[str]]:
    """Group current symbology ``(type, value, mic, figi)`` rows into collisions.

    Returns only keys ``(symbol_type, symbol_value, mic)`` that map to **>1**
    distinct ``composite_figi`` — the MIC is part of the key, so the same ticker
    on two exchanges is not a collision. (Pure.)
    """
    by_key: dict[tuple[str, str, str | None], set[str]] = {}
    for symbol_type, symbol_value, mic, figi in rows:
        by_key.setdefault((symbol_type, symbol_value, mic), set()).add(figi)
    return {k: v for k, v in by_key.items() if len(v) > 1}


def check_identity_completeness(conn: psycopg.Connection) -> CheckResult:
    """Active securities need a current ticker + exactly one current name."""
    active = {r[0] for r in conn.execute(
        "SELECT composite_figi FROM securities WHERE status = 'active'").fetchall()}
    with_ticker = {r[0] for r in conn.execute(
        "SELECT DISTINCT composite_figi FROM security_symbology "
        "WHERE symbol_type = 'ticker' AND valid_to IS NULL").fetchall()}
    with_name = {r[0] for r in conn.execute(
        "SELECT composite_figi FROM security_names WHERE valid_to IS NULL").fetchall()}
    multi_name = [r[0] for r in conn.execute(
        "SELECT composite_figi FROM security_names WHERE valid_to IS NULL "
        "GROUP BY composite_figi HAVING count(*) > 1").fetchall()]

    failures = [f"{f}: no current ticker" for f in sorted(find_missing(active, with_ticker))]
    failures += [f"{f}: no current name" for f in sorted(find_missing(active, with_name))]
    failures += [f"{f}: multiple current names" for f in sorted(multi_name)]
    return CheckResult.from_items(
        "identity_completeness",
        checked=len(active),
        failures=failures,
        detail=f"{len(active)} active securities checked",
    )


def check_ticker_collisions(conn: psycopg.Connection) -> CheckResult:
    """No current (type, value, mic) maps to more than one composite_figi."""
    rows = conn.execute(
        "SELECT symbol_type, symbol_value, mic, composite_figi FROM security_symbology "
        "WHERE valid_to IS NULL"
    ).fetchall()
    collisions = find_collisions(rows)
    failures = [
        f"{st}:{sv}@{mic or '-'} -> {sorted(figis)}"
        for (st, sv, mic), figis in sorted(collisions.items())
    ]
    return CheckResult.from_items(
        "symbology_uniqueness",
        checked=len(rows),
        failures=failures,
        detail=f"{len(rows)} current symbology rows; {len(collisions)} true collision(s)",
    )


def check_symbology_transitions(conn: psycopg.Connection) -> CheckResult:
    """SCD transition integrity (Story 1.10 — the V3 AC restored).

    One OPEN row per (figi, symbol_type): duplicates mean a rename ran without
    closing the predecessor (the pre-1.10 failure mode) — FAIL. A CLOSED row on a
    non-delisted security should have a successor starting exactly at its
    ``valid_to`` (the boundary-day handoff) — a gap is a WARN: the identifier
    history has a hole the as-of query answers with nothing.
    """
    total = conn.execute("SELECT count(*) FROM security_symbology").fetchone()[0]
    duplicate_open = conn.execute(
        """
        SELECT composite_figi, symbol_type, count(*)
          FROM security_symbology
         WHERE valid_to IS NULL
         GROUP BY composite_figi, symbol_type
        HAVING count(*) > 1
        """
    ).fetchall()
    failures = [f"{figi}/{stype}: {n} open rows" for figi, stype, n in duplicate_open]
    # Overlapping effective ranges within one (figi, type) — the other half of
    # the V3 overlap AC. Both-open pairs are excluded (already reported above);
    # the schema EXCLUDE can't catch these because it keys on (type, value, mic).
    overlaps = conn.execute(
        """
        SELECT DISTINCT a.composite_figi, a.symbol_type
          FROM security_symbology a
          JOIN security_symbology b
            ON b.composite_figi = a.composite_figi
           AND b.symbol_type = a.symbol_type
           AND b.ctid <> a.ctid
           AND daterange(a.valid_from, a.valid_to, '[)')
            && daterange(b.valid_from, b.valid_to, '[)')
         WHERE NOT (a.valid_to IS NULL AND b.valid_to IS NULL)
        """
    ).fetchall()
    failures += [f"{figi}/{stype}: overlapping effective ranges" for figi, stype in overlaps]
    orphans = conn.execute(
        """
        SELECT c.composite_figi, c.symbol_type, c.symbol_value, c.valid_to
          FROM security_symbology c
          JOIN securities s USING (composite_figi)
         WHERE c.valid_to IS NOT NULL AND s.status <> 'delisted'
           AND NOT EXISTS (
               SELECT 1 FROM security_symbology n
                WHERE n.composite_figi = c.composite_figi
                  AND n.symbol_type = c.symbol_type
                  AND n.valid_from = c.valid_to
           )
        """
    ).fetchall()
    warnings = [
        f"{figi}/{stype} {value!r} closed {closed} with no successor"
        for figi, stype, value, closed in orphans
    ]
    return CheckResult.from_items(
        "symbology_transitions",
        checked=total,
        failures=failures,
        warnings=warnings,
        detail=(
            f"{total} symbology rows; {len(duplicate_open)} duplicate-open, "
            f"{len(overlaps)} overlapping, {len(orphans)} closed-without-successor"
        ),
    )
