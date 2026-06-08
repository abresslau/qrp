"""psycopg connections + sym-location helper for the operate package.

Operate owns the ``qrp`` database (the job ledger) and is sym's control plane: it runs
sym's CLI ops out-of-process. Self-contained: builds DSNs from the libpq-standard PG*
instance creds (PGHOST/PGPORT/PGUSER/PGPASSWORD). No qrp_api import.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "qrp"  # the job ledger lives in the qrp database


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
    """Connect to this package's database (the qrp job ledger) or a named one."""
    return psycopg.connect(_dsn(dbname), connect_timeout=5)


def sym_project_dir() -> Path:
    """Where sym's CLI lives (cwd for the Operate subprocess).

    Interim: folds away when sym becomes a workspace member and Operate calls it
    library-first (structure-doc step 4 / D3). Override with SYM_PROJECT_DIR.
    """
    _load_cwd_env()
    env = os.environ.get("SYM_PROJECT_DIR")
    return Path(env) if env else Path("C:/Projects/sym")
