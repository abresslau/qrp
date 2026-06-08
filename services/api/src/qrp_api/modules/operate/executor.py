"""Out-of-process executor for sym ops.

Each Operate job spawns ``uv run sym <op> ...`` as a SUBPROCESS (a real OS process,
out of the web process) in the sym project dir, supervised by a daemon thread that
streams the tail of its output into ``qrp.job`` and records exit/status. A Postgres
**advisory lock** keyed on (op, args) guarantees one concurrent run per operation.

Only sym's OWN allowlisted, idempotent CLI ops are runnable; writers are flagged so the
API can require explicit confirmation. We never touch sym's schema — sym's commands own
their own writes, and sym's pipeline_run_log/validation_run_log stay the system-of-record.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from qrp_api.config import db_dsn, sym_project_dir

# Tail of combined stdout/stderr kept on the job row (chars).
_OUTPUT_TAIL = 12000


@dataclass(frozen=True)
class Op:
    key: str
    label: str
    argv: tuple[str, ...]          # base sym CLI args (before any user args)
    writes: bool                   # mutates sym DATA (never schema) -> needs confirm
    takes_universe: bool = False   # appends a universe_id arg
    note: str = ""


# Allowlist. Read-mostly ops run freely; writers require confirm=true at the API.
OPS: dict[str, Op] = {
    "validate": Op(
        "validate", "Validate (integrity gate)", ("validate",), writes=False,
        note="Cross-layer checks; exit 2 means it ran and found issues (see output).",
    ),
    "universe_monitor": Op(
        "universe_monitor", "Universe monitor", ("universe", "monitor"), writes=False,
        takes_universe=True,
        note="Discovers membership changes; gated proposals, no direct apply.",
    ),
    "universe_refresh": Op(
        "universe_refresh", "Universe refresh", ("universe", "refresh"), writes=True,
        takes_universe=True, note="Re-runs provider + resolve + project (writes membership).",
    ),
    "recompute": Op(
        "recompute", "Recompute returns", ("recompute",), writes=True,
        note="Materializes fact_returns across the lookback (writes; can be long).",
    ),
}


def _advisory_key(op: str, args: list[str]) -> int:
    """Stable 63-bit advisory-lock key from op+args (Postgres bigint)."""
    h = hash((op, tuple(args))) & 0x7FFFFFFFFFFFFFFF
    return h


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_job(job_id: int, op: Op, args: list[str]) -> None:
    """Worker body (daemon thread): hold an advisory lock, run the subprocess, record result."""
    conn = psycopg.connect(db_dsn())
    conn.autocommit = True
    key = _advisory_key(op.key, args)
    try:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
        if not got:
            conn.execute(
                "UPDATE qrp.job SET status='rejected', error=%s, finished_at=%s WHERE job_id=%s",
                ("another run of this operation holds the lock", _now(), job_id),
            )
            return
        try:
            conn.execute(
                "UPDATE qrp.job SET status='running', started_at=%s WHERE job_id=%s",
                (_now(), job_id),
            )
            argv = ["uv", "run", "sym", *op.argv, *args]
            try:
                proc = subprocess.run(
                    argv,
                    cwd=str(sym_project_dir()),
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
            except FileNotFoundError as exc:
                conn.execute(
                    "UPDATE qrp.job SET status='failed', error=%s, finished_at=%s WHERE job_id=%s",
                    (f"could not launch op: {exc}", _now(), job_id),
                )
                return
            except subprocess.TimeoutExpired:
                conn.execute(
                    "UPDATE qrp.job SET status='failed', error=%s, finished_at=%s WHERE job_id=%s",
                    ("op timed out after 1800s", _now(), job_id),
                )
                return
            combined = (proc.stdout or "") + (proc.stderr or "")
            tail = combined[-_OUTPUT_TAIL:]
            status = "success" if proc.returncode == 0 else "failed"
            conn.execute(
                "UPDATE qrp.job SET status=%s, exit_code=%s, output=%s, finished_at=%s "
                "WHERE job_id=%s",
                (status, proc.returncode, tail, _now(), job_id),
            )
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
    except Exception as exc:  # noqa: BLE001 — never let a worker die silently
        try:
            conn.execute(
                "UPDATE qrp.job SET status='failed', error=%s, finished_at=%s WHERE job_id=%s",
                (f"executor error: {exc}", _now(), job_id),
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        conn.close()


def launch(job_id: int, op: Op, args: list[str]) -> None:
    """Spawn the supervising daemon thread (returns immediately)."""
    t = threading.Thread(target=_run_job, args=(job_id, op, args), daemon=True)
    t.start()
