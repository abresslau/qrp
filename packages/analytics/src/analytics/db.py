"""psycopg connections for the analytics package.

Analytics has no database of its own: it reads the portfolios database (weights) and the
sym hub (returns). Self-contained: builds DSNs from the libpq-standard PG* instance creds
(PGHOST/PGPORT/PGUSER/PGPASSWORD). No qrp_api import — this package is standalone-shaped.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "portfolios"  # analytics' primary read; it owns no database of its own


def _load_cwd_env() -> None:
    p = Path(".env")
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _dsn(dbname: str) -> str:
    _load_cwd_env()
    override = os.environ.get(f"{dbname.upper()}_DATABASE_URL")
    if override:
        return override
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    user = os.environ.get("PGUSER", "postgres")
    parts = [f"host={host}", f"port={port}", f"dbname={dbname}", f"user={user}"]
    pw = os.environ.get("PGPASSWORD")
    if pw:
        parts.append(f"password={pw}")
    return " ".join(parts)


def connect(dbname: str = _OWN) -> psycopg.Connection:
    """Connect to a named database (defaults to portfolios — analytics' weights source)."""
    return psycopg.connect(_dsn(dbname), connect_timeout=5)


def hub() -> psycopg.Connection:
    """The sym hub — read-only by convention."""
    return connect("sym")
