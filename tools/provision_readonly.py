"""Provision the least-privilege ``qrp_readonly`` Postgres role (Story QH.3).

Consumers read the sym package over this role so that reads-are-read-only is enforced by
the database engine, not by code-review convention — the psycopg analogue of the DuckDB
``ATTACH READ_ONLY`` guarantee (``tools/duckdb_spike.py``). The role gets ``SELECT`` on
EXACTLY the AR-R3 read surface (``qrp_api.sym_contract.SYM_READ_SURFACE`` — the single
source shared with the topology-discipline gate) and nothing else: no write, no DDL, no
access to sym-internal relations.

Idempotent: re-running creates-or-refreshes the role's password and re-asserts the grants
(REVOKE-then-GRANT, so a removed surface entry's privilege is actually withdrawn).

Usage (from the repo root):
    uv run python tools/provision_readonly.py            # create/refresh role + grants
    uv run python tools/provision_readonly.py --check     # report state, change nothing

Credentials: the ADMIN connection uses the repo ``.env`` ``PG*`` vars (the privileged
instance creds); the role's own password comes from ``PGRO_PASSWORD``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from qrp_api.sym_contract import READONLY_ROLE, SYM_READ_SURFACE

REPO = Path(__file__).resolve().parents[1]
SYM_DB = "sym"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = REPO / ".env"
    if p.is_file():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _admin_conn(env: dict[str, str], dbname: str) -> psycopg.Connection:
    if "PGPASSWORD" not in env:
        raise SystemExit("PGPASSWORD missing from .env — provisioning needs admin creds")
    conn = psycopg.connect(
        host=env.get("PGHOST", "localhost"), port=env.get("PGPORT", "5432"),
        user=env.get("PGUSER", "postgres"), password=env["PGPASSWORD"],
        dbname=dbname, connect_timeout=5,
    )
    conn.autocommit = True  # role DDL + grants run outside an explicit transaction
    return conn


def _existing_grants(sym: psycopg.Connection) -> set[str]:
    """Relations in ``public`` the role currently holds ANY privilege on."""
    rows = sym.execute(
        "SELECT table_name FROM information_schema.role_table_grants "
        "WHERE grantee = %s AND table_schema = 'public'",
        (READONLY_ROLE,),
    ).fetchall()
    return {r[0] for r in rows}


def check(env: dict[str, str]) -> int:
    with _admin_conn(env, "postgres") as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (READONLY_ROLE,)
        ).fetchone()
    if not exists:
        print(f"role {READONLY_ROLE!r}: ABSENT (run without --check to provision)")
        return 1
    with _admin_conn(env, SYM_DB) as sym:
        granted = _existing_grants(sym)
    missing = SYM_READ_SURFACE - granted
    extra = granted - SYM_READ_SURFACE  # privileges OUTSIDE the contract = a leak
    print(f"role {READONLY_ROLE!r}: present; SELECT on {len(granted & SYM_READ_SURFACE)}"
          f"/{len(SYM_READ_SURFACE)} surface relations")
    if missing:
        print(f"  MISSING grants (surface relations not granted): {sorted(missing)}")
    if extra:
        print(f"  LEAK (granted outside the read surface): {sorted(extra)}")
    return 0 if not missing and not extra else 1


def provision(env: dict[str, str]) -> int:
    pw = env.get("PGRO_PASSWORD")
    if not pw:
        raise SystemExit("PGRO_PASSWORD missing from .env — the read-only role needs a password")

    # 1) Role + database CONNECT (cluster-global role; runs from the postgres database).
    with _admin_conn(env, "postgres") as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (READONLY_ROLE,)
        ).fetchone()
        role = sql.Identifier(READONLY_ROLE)
        if exists:
            admin.execute(sql.SQL("ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                                  "NOBYPASSRLS PASSWORD {}").format(role, sql.Literal(pw)))
        else:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                                  "NOBYPASSRLS PASSWORD {}").format(role, sql.Literal(pw)))
        admin.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
            sql.Identifier(SYM_DB), role))
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(SYM_DB), role))

    # 2) Schema USAGE + per-relation SELECT on EXACTLY the read surface (run inside sym).
    with _admin_conn(env, SYM_DB) as sym:
        role = sql.Identifier(READONLY_ROLE)
        present = {
            r[0] for r in sym.execute(
                "SELECT relname FROM pg_class WHERE relkind IN ('r','v','m','p') "
                "AND relnamespace = 'public'::regnamespace"
            ).fetchall()
        }
        granted = [r for r in sorted(SYM_READ_SURFACE) if r in present]
        skipped = [r for r in sorted(SYM_READ_SURFACE) if r not in present]  # named, not dropped
        # The REVOKE-then-GRANT surface swap is ATOMIC: a crash mid-way must not leave a
        # previously-working role stripped of all access. autocommit was on for the read
        # above; turn it off so the mutations commit (or roll back) as one transaction.
        sym.autocommit = False
        with sym.transaction():
            sym.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
            sym.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(role))
            sym.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            for rel in granted:
                sym.execute(sql.SQL("GRANT SELECT ON public.{} TO {}").format(
                    sql.Identifier(rel), role))
    print(f"{READONLY_ROLE}: granted SELECT on {len(granted)}/{len(SYM_READ_SURFACE)} "
          f"read-surface relations; CONNECT on {SYM_DB}; no write, no DDL")
    if skipped:
        print(f"  WARNING: surface relations absent from the sym DB (not granted): {skipped}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report role state, change nothing")
    args = ap.parse_args()
    env = _load_env()
    return check(env) if args.check else provision(env)


if __name__ == "__main__":
    sys.exit(main())
