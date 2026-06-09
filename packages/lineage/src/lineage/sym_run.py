"""Run a ``sym`` CLI subcommand as a subprocess from inside a Dagster asset.

This keeps the data loads fully decoupled: Dagster orchestrates *when* a step runs, but
each step still executes through the **exact same** ``sym`` CLI an operator would type by
hand. If Dagster is ever down, the human runs the identical command — nothing about sym
changes, and the "every process runs standalone" requirement is preserved by construction.
"""

from __future__ import annotations

import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from dagster import MaterializeResult, MetadataValue


@lru_cache
def repo_root() -> Path:
    """Locate the monorepo root (the dir containing platform.toml), searching upward
    from the current working directory, then from this file. Falls back to the known path."""
    for base in (Path.cwd(), Path(__file__).resolve()):
        for parent in (base, *base.parents):
            if (parent / "platform.toml").is_file():
                return parent
    return Path("C:/Projects/qrp")


def run_sym(context, *args: str, db: str = "sym") -> MaterializeResult:
    """Invoke ``sym <args>`` via the active interpreter and return a MaterializeResult
    carrying the command, duration, and a tail of stdout as run metadata."""
    cmd = [sys.executable, "-m", "sym.cli", *args]
    pretty = "sym " + " ".join(args)
    context.log.info(f"materialize via: {pretty}")
    started = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=str(repo_root()), capture_output=True, text=True
    )
    duration = round(time.monotonic() - started, 2)
    out_tail = (proc.stdout or "")[-2000:]
    if proc.returncode != 0:
        context.log.error((proc.stderr or "")[-2000:])
        raise RuntimeError(f"`{pretty}` exited {proc.returncode}")
    return MaterializeResult(
        metadata={
            "command": MetadataValue.text(pretty),
            "database": MetadataValue.text(db),
            "duration_s": MetadataValue.float(duration),
            "stdout_tail": MetadataValue.md(f"```\n{out_tail}\n```"),
        }
    )
