"""psycopg connections for the equity package.

Only the database name is given; host/port/user/password come from the libpq-standard PG*
environment (PGHOST/PGPORT/PGUSER/PGPASSWORD), loaded from a .env if present. No qrp_api/sym
import — this package is standalone-shaped (the `rates`/`commodities`/`fx` pattern). Override the
database with ``EQUITY_DATABASE_URL`` (whole DSN) or rename it with ``EQUITY_DB_NAME``.

The equity DB uses the ``public`` schema (like sym), NOT an ``equity`` schema — the engine
modules moved verbatim from sym keep unqualified table names, so this is the lowest-churn split
for the largest table set. equity reads sym identity/calendar through an INJECTED read-only sym
connection (see ``sym_connect``); equity itself never imports sym.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "equity"


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


def sym_connect() -> psycopg.Connection:
    """Open a connection to the sym DB for identity/symbology/calendar READS.

    equity's ingest resolver and returns loader need sym's ``securities``/``security_symbology``/
    ``trading_calendar`` (read-only). This is a convenience for standalone ``equity`` CLI use; the
    sym-orchestrated paths (``sym load``/``recompute``/``eod``) pass their own sym connection in, so
    equity stays sym-import-free either way.
    """
    _load_env()
    name = os.environ.get("SYM_DB_NAME", "sym")
    target = os.environ.get("SYM_DATABASE_URL") or f"dbname={name}"
    return psycopg.connect(target, connect_timeout=5)
