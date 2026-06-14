"""Story QH.3 — the least-privilege sym read role.

Two layers:
- DB-free unit tests pin the credential-resolution precedence (no Postgres needed);
- a live-gated integration test proves the physical guarantee — the psycopg analogue of
  ``tools/duckdb_spike.py`` claim 3: a write to sym through the read path is refused by
  the engine, with the RIGHT reason (permission denied), not merely "an error". It SKIPS
  (never fails) when the role isn't provisioned, so DB-free CI stays green.
"""

from __future__ import annotations

import psycopg
import pytest

from qrp_api import config
from qrp_api.sym_contract import READONLY_ROLE, SYM_INTERNAL_RELATIONS, SYM_READ_SURFACE

# ---------------------------------------------------------------- unit (DB-free)


def test_sym_readonly_dsn_url_override_wins(monkeypatch):
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    monkeypatch.setenv("SYM_READONLY_URL", "postgresql://ro:pw@h:5/sym")
    monkeypatch.setenv("PGRO_USER", "ignored")  # URL override takes precedence
    assert config.sym_readonly_dsn() == "postgresql://ro:pw@h:5/sym"


def test_sym_readonly_dsn_builds_from_role_creds(monkeypatch):
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    monkeypatch.delenv("SYM_READONLY_URL", raising=False)
    monkeypatch.setenv("PGHOST", "db.host")
    monkeypatch.setenv("PGPORT", "6000")
    monkeypatch.setenv("PGRO_USER", "qrp_readonly")
    monkeypatch.setenv("PGRO_PASSWORD", "s3cr3t")
    monkeypatch.delenv("SYM_DB_NAME", raising=False)
    dsn = config.sym_readonly_dsn()
    assert "user=qrp_readonly" in dsn
    assert "dbname=sym" in dsn
    assert "host=db.host" in dsn and "port=6000" in dsn
    assert "password='s3cr3t'" in dsn


def test_sym_readonly_dsn_quotes_special_passwords(monkeypatch):
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    monkeypatch.delenv("SYM_READONLY_URL", raising=False)
    monkeypatch.setenv("PGRO_USER", "qrp_readonly")
    monkeypatch.setenv("PGRO_PASSWORD", r"pa ss'wo\rd")
    dsn = config.sym_readonly_dsn()
    assert r"password='pa ss\'wo\\rd'" in dsn  # libpq keyword-DSN escaping preserved


def test_sym_readonly_dsn_falls_back_to_full_creds_when_unprovisioned(monkeypatch):
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    monkeypatch.delenv("SYM_READONLY_URL", raising=False)
    monkeypatch.delenv("PGRO_USER", raising=False)
    monkeypatch.setattr(config, "db_dsn", lambda: "dbname=sym user=postgres")
    assert config.sym_readonly_dsn() == "dbname=sym user=postgres"


def test_standalone_connect_routes_sym_readonly_but_not_own(monkeypatch):
    """The package ``connect()`` sends a sym read to the read-only target and its OWN
    database to the full-cred path — the central routing that makes Task 3 fall out."""
    from signals import db as signals_db

    monkeypatch.setattr(signals_db, "_load_env", lambda: None)
    monkeypatch.setattr(signals_db, "_sym_readonly_target", lambda: "RO_TARGET")
    captured: list[str] = []
    monkeypatch.setattr(signals_db.psycopg, "connect",
                        lambda target, **kw: captured.append(target) or object())

    signals_db.connect("sym")
    signals_db.connect()  # _OWN == "signals"
    assert captured[0] == "RO_TARGET"          # foreign sym read -> read-only role
    assert captured[1] == "dbname=signals"     # own database -> full creds


def test_read_surface_and_internal_are_disjoint():
    # the provisioner grants SELECT on the surface; the two sets must never overlap or a
    # sym-internal relation would be both granted and asserted off-limits.
    assert SYM_READ_SURFACE.isdisjoint(SYM_INTERNAL_RELATIONS)


# ---------------------------------------------------------------- live (gated)


def _readonly_sym_conn() -> psycopg.Connection | None:
    """A sym connection through the package read path, ONLY if it lands on the read-only
    role. Returns None (→ skip) when sym is unreachable or the role isn't provisioned
    (the fallback would connect as the full-cred user — not what this test asserts)."""
    try:
        from signals.db import connect

        conn = connect("sym")
    except Exception:
        return None
    who = conn.execute("SELECT current_user").fetchone()[0]
    if who != READONLY_ROLE:
        conn.close()
        return None
    return conn


def test_readonly_role_reads_surface_but_refuses_writes_and_internals():
    conn = _readonly_sym_conn()
    if conn is None:
        pytest.skip(f"{READONLY_ROLE} not provisioned / sym unreachable — live check skipped")
    try:
        # (a) an allowlisted read works
        n = conn.execute("SELECT count(*) FROM securities").fetchone()[0]
        assert n >= 0

        # (b) a sym-INTERNAL relation is not readable (surface is least-privilege)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM prices_raw LIMIT 1")
        conn.rollback()

        # (c) writes + DDL are PHYSICALLY refused — for the right reason (permission
        # denied), the duckdb_spike.py lesson: a blanket except would bless any error.
        for stmt in (
            "INSERT INTO securities (composite_figi) VALUES ('QH3PROBE0000')",
            "UPDATE securities SET status = status",
            "DELETE FROM securities WHERE composite_figi = 'QH3PROBE0000'",
            "CREATE TABLE qh3_probe (x int)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)
            conn.rollback()
    finally:
        conn.close()
