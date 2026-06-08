"""psycopg connection helper (reads sym's database; read-only by convention)."""

from __future__ import annotations

import psycopg

from qrp_api.config import db_dsn


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Open a connection. Defaults to the sym DB; pass a package DSN (e.g. ``macro_dsn()``)
    to reach a package that owns its own database under the DB-per-package topology."""
    return psycopg.connect(dsn or db_dsn(), connect_timeout=5)
