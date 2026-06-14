"""psycopg connection helper for the gateway's first-party sym "See" module."""

from __future__ import annotations

import psycopg

from qrp_api.config import db_dsn


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Open a connection (full credentials, read-only by convention).

    With no argument, connects to the sym package's database with full credentials. This
    helper serves the gateway's FIRST-PARTY sym "See" surface (``modules/sym``: Overview,
    Explorer, Universes, Heat map, Attention, Validation) — QRP's own observability window
    into sym. That surface reads sym broadly, INCLUDING sym-internal relations outside the
    AR-R3 cross-package read surface (``universe``, ``prices_raw``, ``gics_scd``,
    ``price_gaps``, the review/validation logs …), so the least-privilege ``qrp_readonly``
    role (Story QH.3) — granted SELECT on the 10-relation surface ONLY — physically cannot
    serve it. It is read-only by convention (only ever SELECTs); QRP never writes sym
    (NFR-1) and sym mutations go through Operate's subprocess op-exec, never this helper.

    The Story QH.3 physical read-only guarantee covers the CROSS-PACKAGE consumers (the 8
    ``packages/*/db.py`` ``connect("sym")`` sites + Operate's history read), which route
    through ``qrp_readonly`` in their own ``db.py`` helpers. This first-party broad reader
    is the serving-path analogue of the ``lineage`` full-cred exception (see deferred-work);
    a broad introspection-scoped read-only role would harden it physically — a follow-up.

    Pass an explicit package DSN (e.g. ``package_dsn("macro")``) to reach a package that
    owns its own database under the DB-per-package topology.
    """
    return psycopg.connect(dsn or db_dsn(), connect_timeout=5)
