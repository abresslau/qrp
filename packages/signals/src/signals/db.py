"""psycopg connections for the signal package.

Self-contained: builds DSNs from the libpq-standard PG* instance creds
(PGHOST/PGPORT/PGUSER/PGPASSWORD); names its own database and the sym hub. Loads a CWD
.env as a convenience. No qrp_api import — this package is standalone-shaped.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "signals"


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
    """Connect to this package's database (default) or a named one."""
    return psycopg.connect(_dsn(dbname), connect_timeout=5)


def hub() -> psycopg.Connection:
    """The sym hub — read-only by convention."""
    return connect("sym")
