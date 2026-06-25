"""psycopg connections for the universe package.

Only the database name is given; host/port/user/password come from the libpq-standard PG*
environment (PGHOST/PGPORT/PGUSER/PGPASSWORD), loaded from a .env if present. No qrp_api/sym
import — this package is standalone-shaped (the `rates`/`commodities`/`fx` pattern). Override the
database with ``UNIVERSE_DATABASE_URL`` (whole DSN) or rename it with ``UNIVERSE_DB_NAME``.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "universe"


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
    """Connect to this package's own database on the shared instance (PG* env supplies the rest).

    The ``search_path`` is pinned to the ``universe`` schema (then ``public`` for the shared
    extensions), so the domain modules address their tables by bare name (``universe_membership``,
    ``membership_event``, …) and resolve to ``universe.*`` — the membership SQL moved out of sym
    verbatim. External readers (data-monitor, backtest, signals) schema-qualify instead.
    """
    _load_env()
    name = dbname or os.environ.get(f"{_OWN.upper()}_DB_NAME", _OWN)
    target = os.environ.get(f"{name.upper()}_DATABASE_URL") or f"dbname={name}"
    # autocommit=True so the SET below doesn't leave the connection in an open transaction — write
    # paths that set ``conn.autocommit = True`` would otherwise raise on an INTRANS conn. Reads
    # unaffected; explicit transactions still wrap writes.
    conn = psycopg.connect(target, connect_timeout=5, autocommit=True)
    conn.execute("SET search_path TO universe, public")
    return conn
