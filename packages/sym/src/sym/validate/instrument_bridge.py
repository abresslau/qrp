"""Equity ↔ instrument bridge integrity (the `sym_id`/`composite_figi` spine decision).

QRP deliberately runs two identity keys (Option A, 2026-06-09): `composite_figi` is the
natural key of the equity warehouse; `sym_id` is the vendor-neutral surrogate spine for
cross-asset identity (indexes have no FIGI, so they can't key on one). The two are bridged
1:1 — every `securities` row maps to an `instrument(kind='equity')` via a `composite_figi`
xref (``backfill_equity_instruments``), and composite_figi is "just one external id among
many" on that spine.

The bridge is maintained in code (no hard FK from securities → instrument): refreshed where
securities are created (``run_universe_load``) and by the nightly EOD ``map`` step. This check
asserts it stays complete AND points at an *equity* instrument (not merely that some xref row
exists), catching two hole kinds:

* **unmapped security** — a ``securities`` row with no ``composite_figi`` xref resolving to a
  ``kind='equity'`` instrument. Actionable: re-run ``backfill_equity_instruments`` (it mints
  the missing instrument + xref).
* **orphan equity instrument** — an ``instrument(kind='equity')`` with no ``composite_figi``
  xref. A partial-insert artifact (an instrument row written without its xref); the backfill
  keys off ``securities`` so it will NOT repair this — it needs manual reconciliation.

Either hole makes cross-asset joins (equity returns ↔ index returns via ``sym_id``) drop rows
unseen.
"""

from __future__ import annotations

import psycopg

from sym.identity.instrument import EQUITY, SRC_COMPOSITE_FIGI
from sym.validate.results import CheckResult


def find_unmapped(security_figis: set[str], equity_mapped_figis: set[str]) -> set[str]:
    """Securities not bridged to a kind='equity' instrument via a composite_figi xref (pure)."""
    return {f for f in security_figis if f and f not in equity_mapped_figis}


def find_orphan_instruments(equity_sym_ids: set[int], figi_xref_sym_ids: set[int]) -> set[int]:
    """Equity instruments with no composite_figi xref (pure)."""
    return {s for s in equity_sym_ids if s not in figi_xref_sym_ids}


def check_equity_instrument_bridge(conn: psycopg.Connection) -> CheckResult:
    """Assert every security bridges 1:1 to an equity instrument via a composite_figi xref."""
    security_figis = {
        r[0] for r in conn.execute("SELECT composite_figi FROM securities").fetchall()
    }
    # FIGIs that resolve THROUGH the xref to a real kind='equity' instrument — the join to
    # `instrument` is what makes this a true equity bridge, not just "an xref row exists".
    equity_mapped_figis = {
        r[0]
        for r in conn.execute(
            "SELECT x.value FROM instrument_xref x "
            "JOIN instrument i ON i.sym_id = x.sym_id "
            "WHERE x.source = %s AND i.kind = %s",
            (SRC_COMPOSITE_FIGI, EQUITY),
        ).fetchall()
    }
    equity_sym_ids = {
        r[0]
        for r in conn.execute(
            "SELECT sym_id FROM instrument WHERE kind = %s", (EQUITY,)
        ).fetchall()
    }
    figi_xref_sym_ids = {
        r[0]
        for r in conn.execute(
            "SELECT sym_id FROM instrument_xref WHERE source = %s", (SRC_COMPOSITE_FIGI,)
        ).fetchall()
    }
    unmapped = find_unmapped(security_figis, equity_mapped_figis)
    orphans = find_orphan_instruments(equity_sym_ids, figi_xref_sym_ids)
    failures = [
        f"securities {figi}: no equity-instrument mapping (run backfill_equity_instruments)"
        for figi in sorted(unmapped)
    ]
    failures += [
        f"instrument {sym_id} (equity): no composite_figi xref (partial insert; manual fix)"
        for sym_id in sorted(orphans)
    ]
    return CheckResult.from_items(
        "equity_instrument_bridge",
        checked=len(security_figis),
        failures=failures,
        detail=(
            f"{len(security_figis)} securities; {len(unmapped)} unmapped, "
            f"{len(orphans)} orphan equity instrument(s)"
        ),
    )
