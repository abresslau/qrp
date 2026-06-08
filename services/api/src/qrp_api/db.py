"""psycopg connection helper (reads sym's database; read-only by convention)."""

from __future__ import annotations

import psycopg

from qrp_api.config import db_dsn


def connect() -> psycopg.Connection:
    return psycopg.connect(db_dsn(), connect_timeout=5)
