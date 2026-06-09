"""Equity ↔ instrument bridge integrity (the `sym_id`/`composite_figi` spine decision).

QRP deliberately runs two identity keys (Option A, 2026-06-09): `composite_figi` is the
natural key of the equity warehouse; `sym_id` is the vendor-neutral surrogate spine for
cross-asset identity (indexes have no FIGI, so they can't key on one). The two are bridged
1:1 — every `securities` row maps to an `instrument(kind='equity')` via a `composite_figi`
xref (``backfill_equity_instruments``), and composite_figi is "just one external id among
many" on that spine.

That bridge is backfilled in code (no hard FK from securities → instrument), so it can
silently develop holes: a new security with no instrument row, or an equity instrument
with no figi xref. Either hole makes cross-asset joins (equity returns ↔ index returns via
sym_id) drop rows unseen. This check asserts the bridge stays complete and 1:1; a hole is
actionable — re-run ``backfill_equity_instruments``.
"""

from __future__ import annotations

import psycopg

from sym.identity.instrument import EQUITY, SRC_COMPOSITE_FIGI
from sym.validate.results import CheckResult


def check_equity_instrument_bridge(conn: psycopg.Connection) -> CheckResult:
    """Assert every security maps 1:1 to an equity instrument via a composite_figi xref."""
    unmapped = conn.execute(
        """
        SELECT s.composite_figi
          FROM securities s
         WHERE NOT EXISTS (
             SELECT 1 FROM instrument_xref x
              WHERE x.source = %s AND x.value = s.composite_figi
         )
         ORDER BY s.composite_figi
        """,
        (SRC_COMPOSITE_FIGI,),
    ).fetchall()
    orphan_instruments = conn.execute(
        """
        SELECT i.sym_id
          FROM instrument i
         WHERE i.kind = %s
           AND NOT EXISTS (
             SELECT 1 FROM instrument_xref x
              WHERE x.sym_id = i.sym_id AND x.source = %s
         )
         ORDER BY i.sym_id
        """,
        (EQUITY, SRC_COMPOSITE_FIGI),
    ).fetchall()
    checked = conn.execute("SELECT count(*) FROM securities").fetchone()[0]
    failures = [
        f"securities {r[0]}: no instrument mapping (run backfill_equity_instruments)"
        for r in unmapped
    ]
    failures += [f"instrument {r[0]} (equity): no composite_figi xref" for r in orphan_instruments]
    return CheckResult.from_items(
        "equity_instrument_bridge",
        checked=checked,
        failures=failures,
        detail=(
            f"{checked} securities; {len(unmapped)} unmapped, "
            f"{len(orphan_instruments)} orphan equity instrument(s)"
        ),
    )
