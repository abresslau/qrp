"""psycopg connection helper (defaults to a READ-ONLY connection to sym's database)."""

from __future__ import annotations

import psycopg

from qrp_api.config import sym_readonly_dsn


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Open a connection.

    With no argument, connects to the sym package's database through the least-privilege
    ``qrp_readonly`` role (Story QH.3) — QRP never writes sym (NFR-1); sym mutations go
    through Operate's subprocess op-exec, never this helper. Pass an explicit package DSN
    (e.g. ``package_dsn("macro")``) to reach a package that owns its own database under
    the DB-per-package topology.
    """
    return psycopg.connect(dsn or sym_readonly_dsn(), connect_timeout=5)
