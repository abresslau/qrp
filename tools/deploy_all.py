"""Deploy every per-package Sqitch project from one command (Story QH.5).

The DSN registry below is THE map of the DB-per-package topology: each Sqitch project
directory and the database it owns. The runner creates missing databases (idempotent),
then runs Docker sqitch ``deploy`` + ``verify`` per project (the house deployment
method — no local sqitch). Any failure exits non-zero with the project named.

Usage (from the repo root):
    uv run python tools/deploy_all.py            # create-if-missing + deploy + verify all
    uv run python tools/deploy_all.py --status   # report plan-vs-deployed state, change nothing
    uv run python tools/deploy_all.py --only macro signals   # subset

Credentials come from the repo ``.env`` (PG* variables); sqitch reaches the host
database via ``host.docker.internal``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parents[1]

# project name -> (sqitch project dir, database it owns). The two irregulars are
# explicit: sym's project lives in migrations/; operate owns the `qrp` database
# (the Operate job ledger — see its sqitch.plan comment).
#
# LEGACY, deliberately unregistered: the root `db/` directory is the pre-split `qrp`
# monolith project — it is recorded in the sym database's sqitch registry (deployed
# history) but its net schema effect is nil (create → relocate → drop), so a fresh
# sym rebuild converges without it. Delete-or-keep is a ledgered decision
# (deferred-work.md, Story QH.5).
REGISTRY: dict[str, tuple[Path, str]] = {
    "sym": (REPO / "packages/sym/migrations", "sym"),
    "operate": (REPO / "packages/operate/db", "qrp"),
    "altdata": (REPO / "packages/altdata/db", "altdata"),
    "backtest": (REPO / "packages/backtest/db", "backtest"),
    "macro": (REPO / "packages/macro/db", "macro"),
    "rates": (REPO / "packages/rates/db", "rates"),
    "commodities": (REPO / "packages/commodities/db", "commodities"),
    "fx": (REPO / "packages/fx/db", "fx"),
    "optimiser": (REPO / "packages/optimiser/db", "optimiser"),
    "portfolios": (REPO / "packages/portfolios/db", "portfolios"),
    "signals": (REPO / "packages/signals/db", "signals"),
}


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = REPO / ".env"
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _admin_conn(env: dict[str, str]) -> psycopg.Connection:
    if "PGPASSWORD" not in env:
        raise SystemExit("PGPASSWORD missing from .env — the deployer needs it")
    conn = psycopg.connect(
        host=env.get("PGHOST", "localhost"), port=env.get("PGPORT", "5432"),
        user=env.get("PGUSER", "postgres"), password=env["PGPASSWORD"],
        dbname="postgres", connect_timeout=5,
    )
    conn.autocommit = True  # CREATE DATABASE cannot run inside a transaction
    return conn


def ensure_database(admin: psycopg.Connection, dbname: str) -> bool:
    """Create ``dbname`` if absent. Returns True when it was created."""
    exists = admin.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
    ).fetchone()
    if exists:
        return False
    # identifier-quoted defensively even though dbname comes from the static REGISTRY
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    return True


def _sqitch(project_dir: Path, command: str, dbname: str, env: dict[str, str]) -> tuple[int, str]:
    """Run a sqitch command against ``dbname`` via the Docker image (house method).

    The password travels as SQITCH_PASSWORD through the container environment — never
    in the target URI/argv (process listings and failure output stay password-free).
    """
    target = (
        f"db:pg://{env.get('PGUSER', 'postgres')}"
        f"@host.docker.internal:{env.get('PGPORT', '5432')}/{dbname}"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "-e", "SQITCH_PASSWORD",
         "-v", f"{project_dir}:/repo", "-w", "/repo",
         "sqitch/sqitch", command, target],
        capture_output=True, text=True,
        env={**os.environ, "MSYS_NO_PATHCONV": "1", "SQITCH_PASSWORD": env["PGPASSWORD"]},
    )
    out = (proc.stdout + proc.stderr).strip()
    # ONLY `deploy` exits 1 with "Nothing to deploy" when up to date — that is success.
    # The rescue is command-scoped so a failed verify/status can't ride a stray phrase.
    if command == "deploy" and proc.returncode != 0 and "Nothing to deploy" in out:
        return 0, out
    return proc.returncode, out


def run(only: list[str] | None, status_only: bool) -> int:
    env = _load_env()
    names = only or list(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"unknown project(s): {', '.join(unknown)} (registry: {', '.join(REGISTRY)})")
        return 2
    failures: list[str] = []
    created: list[str] = []
    with _admin_conn(env) as admin:
        for name in names:
            project_dir, dbname = REGISTRY[name]
            if not (project_dir / "sqitch.plan").exists():
                print(f"[{name}] MISSING sqitch.plan at {project_dir}")
                failures.append(name)
                continue
            if status_only:
                code, out = _sqitch(project_dir, "status", dbname, env)
                state = "up to date" if "up-to-date" in out or "Nothing to deploy" in out else (
                    out.splitlines()[-1] if out else f"exit {code}")
                print(f"[{name}] db={dbname}: {state}")
                # status exits 1 for an undeployed database — report, don't fail
                continue
            if ensure_database(admin, dbname):
                created.append(dbname)
                print(f"[{name}] created database {dbname}")
            code, out = _sqitch(project_dir, "deploy", dbname, env)
            if code != 0:
                print(f"[{name}] DEPLOY FAILED:\n{out}")
                failures.append(name)
                continue
            code, out = _sqitch(project_dir, "verify", dbname, env)
            if code != 0:
                print(f"[{name}] VERIFY FAILED:\n{out}")
                failures.append(name)
                continue
            print(f"[{name}] db={dbname}: deployed + verified")
    if status_only:
        return 1 if failures else 0  # a missing plan is a failure in any mode
    print(
        f"\n{len(names) - len(failures)}/{len(names)} projects deployed+verified"
        + (f"; created: {', '.join(created)}" if created else "")
        + (f"; FAILED: {', '.join(failures)}" if failures else "")
    )
    # Provision the qrp_readonly role once sym is in place (Story QH.3). Non-fatal: a
    # missing PGRO_PASSWORD only means consumers fall back to full-cred reads until set.
    # Imported lazily (not at module top) so `--status`/`--help` and a `python -m` import
    # never require the provisioner / qrp_api to be importable.
    if "sym" in names and "sym" not in failures:
        if env.get("PGRO_PASSWORD"):
            try:  # script form puts tools/ on sys.path; -m form needs the package path
                import provision_readonly
            except ModuleNotFoundError:
                from tools import provision_readonly
            provision_readonly.provision(env)
        else:
            print("[qrp_readonly] skipped — set PGRO_PASSWORD in .env to provision the "
                  "read-only role (reads fall back to full creds until then)")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true", help="report state, change nothing")
    ap.add_argument("--only", nargs="+", help="subset of registry project names")
    args = ap.parse_args()
    sys.exit(run(args.only, args.status))
