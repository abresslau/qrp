"""psycopg connections for the operate package.

Only the database name is given; host/port/user/password come from the libpq-standard PG*
environment (PGHOST/PGPORT/PGUSER/PGPASSWORD), loaded from a .env if present. No qrp_api
import — this package is standalone-shaped. Override one database with <DB>_DATABASE_URL.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "qrp"


def _load_env() -> None:
    # Anchored to the repo root (this file is packages/<pkg>/src/<pkg>/db.py), with a CWD
    # fallback — services and workers are not guaranteed to launch from the repo root.
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


def connect(dbname: str = _OWN) -> psycopg.Connection:
    """Connect to a database on the shared instance (PG* env supplies the rest)."""
    _load_env()
    target = os.environ.get(f"{dbname.upper()}_DATABASE_URL") or f"dbname={dbname}"
    return psycopg.connect(target, connect_timeout=5)
