"""Backup and disaster recovery (Story 2.9, AR-14).

The backup captures only source-of-truth data and excludes the recomputable
``fact_returns`` (a deterministic function of raw + factors + calendar, rebuilt by
``sym recompute`` — note the CLI default lookback is ONE YEAR; a full-history
rebuild needs an explicit ``--start_date``). The ``sqitch`` registry is excluded
too — on recovery the schema comes from ``sqitch deploy``, then this dump restores
the data, then recompute rebuilds the derived layer. (``fact_index_returns`` is
also recomputable but is deliberately kept IN the dump — conservative, it is
small.) See ``docs/disaster-recovery.md``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from glob import glob
from pathlib import Path

# Derived tables that `sym recompute` rebuilds deterministically (Epic 3, AR-7),
# so they are excluded from backups -- recovery regenerates them.
RECOMPUTABLE_TABLES = ("fact_returns",)


def backup_args(output_path: str) -> list[str]:
    """pg_dump flags for a DR backup: custom format, source-of-truth only.

    Excludes the ``sqitch`` registry (schema is rebuilt by migrations) and every
    recomputable table (rebuilt by recompute).
    """
    args = ["--format=custom", "--no-owner", "--exclude-schema=sqitch"]
    for table in RECOMPUTABLE_TABLES:
        args.append(f"--exclude-table=public.{table}")
    args += ["--file", output_path]
    return args


def find_pg_dump(name: str = "pg_dump") -> str | None:
    """Locate the pg_dump executable: ``SYM_PG_BIN`` dir, PATH, or a PG install."""
    exe = name + (".exe" if os.name == "nt" else "")
    override = os.environ.get("SYM_PG_BIN")
    if override:
        candidate = Path(override) / exe
        if candidate.is_file():
            return str(candidate)
    on_path = shutil.which(name)
    if on_path:
        return on_path
    for pattern in (
        rf"C:\Program Files\PostgreSQL\*\bin\{exe}",
        f"/usr/lib/postgresql/*/bin/{name}",
        f"/usr/pgsql-*/bin/{name}",
        f"/opt/homebrew/opt/postgresql@*/bin/{name}",
    ):
        # NUMERIC version sort — lexicographic would rank '9.6' above '16' and pick
        # the oldest client against a newer server.
        matches = sorted(glob(pattern), key=lambda p: [int(x) for x in re.findall(r"\d+", p)])
        if matches:
            return matches[-1]  # newest version available
    return None


def run_backup(conninfo: str, output_path: str, *, pg_dump: str | None = None) -> str:
    """Write a DR backup of ``conninfo`` to ``output_path``; returns the path.

    The password (if any) travels via the ``PGPASSWORD`` environment, never on the
    command line — argv is visible to any local process enumerator for the whole
    dump. A failed dump's partial output file is removed so it can never be
    mistaken for a valid backup.
    """
    executable = pg_dump or find_pg_dump()
    if executable is None:
        raise FileNotFoundError(
            "pg_dump not found; set SYM_PG_BIN to the PostgreSQL bin directory "
            "or add the client tools to PATH"
        )
    env = dict(os.environ)
    # Handles both bare and libpq-quoted keyword form (password='...'); a URL-form
    # SYM_DATABASE_URL passes through unchanged (document credentials there yourself).
    match = re.search(r"password=('(?:[^'\\]|\\.)*'|\S+)", conninfo)
    if match:
        password = match.group(1)
        if password.startswith("'") and password.endswith("'"):
            password = password[1:-1].replace("\\'", "'").replace("\\\\", "\\")
        env["PGPASSWORD"] = password
        conninfo = conninfo.replace(match.group(0), "").strip()
    try:
        subprocess.run(
            [executable, *backup_args(output_path), "-d", conninfo], check=True, env=env
        )
    except subprocess.CalledProcessError:
        Path(output_path).unlink(missing_ok=True)  # never leave a truncated dump behind
        raise
    return output_path
