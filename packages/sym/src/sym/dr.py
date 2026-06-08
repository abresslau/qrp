"""Backup and disaster recovery (Story 2.9, AR-14).

The backup captures only source-of-truth data and excludes the recomputable
``fact_returns`` (a deterministic function of raw + factors + calendar, rebuilt by
``sym recompute`` in Epic 3). The ``sqitch`` registry is excluded too — on recovery
the schema comes from ``sqitch deploy``, then this dump restores the data, then
recompute rebuilds the derived layer. See ``docs/disaster-recovery.md``.
"""

from __future__ import annotations

import os
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
        matches = sorted(glob(pattern))
        if matches:
            return matches[-1]  # newest version available
    return None


def run_backup(conninfo: str, output_path: str, *, pg_dump: str | None = None) -> str:
    """Write a DR backup of ``conninfo`` to ``output_path``; returns the path."""
    executable = pg_dump or find_pg_dump()
    if executable is None:
        raise FileNotFoundError(
            "pg_dump not found; set SYM_PG_BIN to the PostgreSQL bin directory "
            "or add the client tools to PATH"
        )
    subprocess.run([executable, *backup_args(output_path), "-d", conninfo], check=True)
    return output_path
