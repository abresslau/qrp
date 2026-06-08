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
