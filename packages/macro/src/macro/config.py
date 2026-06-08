"""macro package config — its OWN database connection settings.

A package owns its connection config: it reads env (a DSN it is *given*), it does NOT walk the
filesystem hunting for a monorepo root. Shared-instance creds come from the libpq-standard `PG*`
env (`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`); this package only names its own database
(`dbname=macro`). `MACRO_DATABASE_URL` overrides the whole DSN. A `.env` in the current working
directory is loaded as a convenience (CWD only — no parent-walking).
"""

from __future__ import annotations

import os
from pathlib import Path

_INSTANCE_DEFAULTS = {"host": "localhost", "port": "5432", "user": "postgres"}


def _load_cwd_env() -> None:
    path = Path(".env")  # CWD only — deliberately not walking parents
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def dsn() -> str:
    """Resolve the macro database DSN from the environment."""
    _load_cwd_env()
    url = os.environ.get("MACRO_DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST", _INSTANCE_DEFAULTS["host"])
    port = os.environ.get("PGPORT", _INSTANCE_DEFAULTS["port"])
    user = os.environ.get("PGUSER", _INSTANCE_DEFAULTS["user"])
    dbname = os.environ.get("MACRO_DB_NAME", "macro")
    parts = [f"host={host}", f"port={port}", f"dbname={dbname}", f"user={user}"]
    password = os.environ.get("PGPASSWORD")
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)
