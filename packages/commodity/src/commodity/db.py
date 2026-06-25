"""psycopg connections for the commodities package.

Only the database name is given; host/port/user/password come from the libpq-standard PG*
environment (PGHOST/PGPORT/PGUSER/PGPASSWORD), loaded from a .env if present. No qrp_api import —
this package is standalone-shaped (the `rates`/`macro` pattern). Override the database with
``COMMODITIES_DATABASE_URL`` (whole DSN) or rename it with ``COMMODITIES_DB_NAME``.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "commodity"


def _load_env() -> None:
    # Anchored to the repo root (this file is packages/<pkg>/src/<pkg>/db.py), with a CWD fallback.
    p = Path(__file__).resolve().parents[4] / ".env"
    if not p.is_file():
        p = Path(".env")
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def connect(dbname: str | None = None) -> psycopg.Connection:
    """Connect to this package's own database on the shared instance (PG* env supplies the rest)."""
    _load_env()
    name = dbname or os.environ.get(f"{_OWN.upper()}_DB_NAME", _OWN)
    target = os.environ.get(f"{name.upper()}_DATABASE_URL") or f"dbname={name}"
    return psycopg.connect(target, connect_timeout=5)
