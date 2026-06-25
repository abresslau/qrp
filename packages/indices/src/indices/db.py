"""psycopg connections for the indices package.

Only the database name is given; host/port/user/password come from the libpq-standard PG*
environment (PGHOST/PGPORT/PGUSER/PGPASSWORD), loaded from a .env if present. No qrp_api/sym
import — this package is standalone-shaped (the ``rates``/``fx``/``equity`` pattern). Override the
database with ``INDICES_DATABASE_URL`` (whole DSN) or rename it with ``INDICES_DB_NAME``.

The index objects live in a dedicated ``indices`` schema (the per-package named-schema convention,
matching fx.*/equity.*/universe.*). The engine + every consumer read the tables UNQUALIFIED; a
DB-level ``search_path`` (set by the indices_schema migration: ``ALTER DATABASE indices SET
search_path TO indices, public``) resolves them on every connection, and this module pins it too for
good measure.

Index facts are keyed on the universal ``sym_id`` identity bridge, which lives in the sym DB; indices
reads it through an INJECTED read-only sym connection (see ``sym_connect``), and reads the membership
roster for the universe→benchmark link from the universe DB (``universe_connect``). indices itself
never imports sym or universe.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "indices"


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
    conn = psycopg.connect(target, connect_timeout=5)
    # Resolve the engine's unqualified table names against the `indices` schema (the DB-level
    # search_path already does this for every connection; pinned here too, self-documenting).
    conn.execute("SET search_path TO indices, public")
    return conn


def sym_connect() -> psycopg.Connection:
    """Open a connection to the sym DB for identity/symbology READS (+ identity WRITES on load).

    The index loaders resolve/ensure instrument identity (``instrument``/``instrument_xref``) and the
    board reads instrument metadata (name/region/country/currency) — all in the sym DB. This is a
    convenience for standalone ``indices`` CLI use; the sym-orchestrated paths (``sym eod``) pass their
    own sym connection in, so indices stays sym-import-free either way.
    """
    _load_env()
    name = os.environ.get("SYM_DB_NAME", "sym")
    target = os.environ.get("SYM_DATABASE_URL") or f"dbname={name}"
    return psycopg.connect(target, connect_timeout=5)


def universe_connect() -> psycopg.Connection:
    """Open a connection to the universe DB for the membership roster (universe→benchmark link)."""
    _load_env()
    name = os.environ.get("UNIVERSE_DB_NAME", "universe")
    target = os.environ.get("UNIVERSE_DATABASE_URL") or f"dbname={name}"
    return psycopg.connect(target, connect_timeout=5)
