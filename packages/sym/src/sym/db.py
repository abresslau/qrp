"""psycopg connection helpers.

Thin wrappers around psycopg so the rest of the package never assembles a
connection string itself — it asks :func:`connect`, which resolves config from
the environment via :mod:`sym.config`.
"""

from __future__ import annotations

import psycopg

from sym.config import load_db_config


def connect(conninfo: str | None = None, *, connect_timeout: int = 5) -> psycopg.Connection:
    """Open a connection to the sym database.

    ``conninfo`` defaults to the value resolved from the environment.
    """
    if conninfo is None:
        conninfo = load_db_config()
    return psycopg.connect(conninfo, connect_timeout=connect_timeout)
