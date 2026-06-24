"""The sym read-surface contract (AR-R3) — the ONE place it is defined.

sym is a read-only upstream peer; consumers may read only the relations named here.
This module is the single source of truth for two consumers that must never drift:

1. ``services/api/tests/test_topology_discipline.py`` — the discipline gate that fails a
   consumer reading anything outside this surface (extend the surface HERE, deliberately);
2. ``tools/provision_readonly.py`` — provisions the ``qrp_readonly`` Postgres role with
   ``SELECT`` on exactly ``SYM_READ_SURFACE`` (Story QH.3), so the role's physical grants
   and the discipline gate can never disagree.

Base tables are the accepted surface until the DuckDB-federation restructure lands
(architecture revision log 2026-06-08); the role + ``ATTACH READ_ONLY`` discipline is the
physical successor to the views-only contract.
"""

from __future__ import annotations

# The least-privilege read-only role consumers use for sym reads (Story QH.3).
READONLY_ROLE = "qrp_readonly"

# AR-R3: the sym read surface consumers may touch. Extend DELIBERATELY — a new entry here
# simultaneously widens the discipline gate AND the role's grants (single source of truth).
SYM_READ_SURFACE = {
    "fact_returns",
    "fact_index_returns",
    "securities",
    "security_symbology",
    "security_names",
    # universe_membership moved to the `universe` peer package + its own DB (no longer a sym read).
    "fundamentals",
    "return_window",
    "instrument",
    "pipeline_run_log",  # Operate's correlated run history (FR-6/FR-8)
    "gics_scd",  # GICS sector/industry — analytics' live portfolio composition (sector donut)
    "exchange",  # exchange→country — the live composition pivot (explorer-style per-stock columns)
    "prices_raw",  # latest EOD volume — the live composition pivot (explorer-style per-stock columns)
    "fact_price_extremes",  # 52-week high/low — the live composition pivot's 52W range bar (Story 3.2-ext)
}

# The known sym public relations OUTSIDE the read surface (kept current by hand from
# sym's migrations; the topology gate's vocabulary guard catches strays naming anything
# newer, so an omission here cannot silently widen the contract). The role is NEVER
# granted SELECT on these.
SYM_INTERNAL_RELATIONS = {
    "prices_review", "trading_calendar",
    "trading_calendar_version",
    # The universe membership tables moved to the `universe` peer package + its own database
    # (universe, membership_event, membership_proposal, universe_member_resolution,
    # universe_monitor_log, universe_accuracy_check). universe_benchmark + the sym-side
    # universe_member_completeness validate-output table STAY in sym.
    "universe_member_completeness", "fx_rate",
    "fx_rate_review", "securities_review_queue", "pipeline_backfill_progress",
    "instrument_xref", "corporate_actions", "currency", "index_levels", "price_gaps",
    "universe_benchmark",
    "v_fx", "v_fx_daily", "v_prices_adjusted", "validation_run_log",
    "fact_index_extremes",  # 52-week index extremes (Story 3.2-ext) — not yet consumed by any API reader
}
