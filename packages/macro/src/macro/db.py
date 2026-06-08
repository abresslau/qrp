"""psycopg connection helper for the macro package (its own database)."""

from __future__ import annotations

import psycopg

from macro.config import dsn


def connect(conninfo: str | None = None) -> psycopg.Connection:
    return psycopg.connect(conninfo or dsn(), connect_timeout=5)
