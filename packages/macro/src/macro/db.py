"""psycopg connections for the macro package.

Only the database name is given; host/port/user/password come from the libpq-standard PG*
environment (PGHOST/PGPORT/PGUSER/PGPASSWORD), loaded from a .env if present. No qrp_api
import — this package is standalone-shaped. Override one database with <DB>_DATABASE_URL.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

_OWN = "macro"


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


def _sym_readonly_target() -> str:
    """Read-only sym access via the least-privilege ``qrp_readonly`` role (Story QH.3).

    sym is a foreign, read-only upstream peer; its read surface is reachable through a
    role that physically refuses writes (SELECT on the AR-R3 surface only), not by
    convention. Precedence: ``SYM_READONLY_URL`` (whole DSN) > ``PGRO_USER`` /
    ``PGRO_PASSWORD`` role creds (host/port from the libpq ``PG*`` env) > the full-cred
    sym DSN as a pre-provision fallback, so a not-yet-provisioned environment still reads.
    """
    url = os.environ.get("SYM_READONLY_URL")
    if url:
        return url
    ro_user = os.environ.get("PGRO_USER")
    if not ro_user:
        return os.environ.get("SYM_DATABASE_URL") or "dbname=sym"
    parts = [f"dbname={os.environ.get('SYM_DB_NAME', 'sym')}", f"user={ro_user}"]
    password = os.environ.get("PGRO_PASSWORD")
    if password:
        quoted = password.replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"password='{quoted}'")
    return " ".join(parts)


def connect(dbname: str = _OWN) -> psycopg.Connection:
    """Connect to a database on the shared instance (PG* env supplies the rest).

    A connection to ``sym`` (a foreign, read-only upstream peer) goes through the
    least-privilege ``qrp_readonly`` role (Story QH.3); this package's own database keeps
    full credentials (it writes there). sym ops are actuated by the Operate subprocess,
    never over this read connection.
    """
    _load_env()
    if dbname == "sym" and dbname != _OWN:
        return psycopg.connect(_sym_readonly_target(), connect_timeout=5)
    target = os.environ.get(f"{dbname.upper()}_DATABASE_URL") or f"dbname={dbname}"
    return psycopg.connect(target, connect_timeout=5)
