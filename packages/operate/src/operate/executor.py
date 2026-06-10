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

import hashlib
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from operate.db import connect

# Tail of combined stdout/stderr kept on the job row (chars).
_OUTPUT_TAIL = 12000
# Child-process budget and heartbeat cadence (Story O.2). The orphan window is
# DERIVED (3x the beat) and interpolated into the gateway's SQL — one knob.
_TIMEOUT_S = 1800
_BEAT_S = 10.0
_STALE_S = int(_BEAT_S * 3)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child AND its descendants.

    ``proc.kill()`` alone kills ``uv``; the sym GRANDCHILD survives and keeps
    writing to the warehouse after the job row says failed — on Windows the
    only reliable tree-kill is taskkill /T. ``wait`` is guarded so a hung
    reaped-state read can't displace the real failure message (constraint 6).
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


@dataclass(frozen=True)
class Op:
    key: str
    label: str
    argv: tuple[str, ...]          # base sym CLI args (before any user args)
    writes: bool                   # mutates sym DATA (never schema) -> needs confirm
    takes_universe: bool = False   # appends a universe_id arg
    takes_scope: bool = False      # appends a load scope arg (universe:<id>)
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
    "universe_review": Op(
        "universe_review", "Universe review digest", ("universe", "review"), writes=False,
        note="Operator digest: pending proposals, stale monitors, accuracy alarms.",
    ),
    "universe_accuracy": Op(
        "universe_accuracy", "Universe accuracy gate", ("universe", "accuracy"),
        writes=False, takes_universe=True,
        note="Cross-checks membership vs the configured reference; exit 2 = alarm.",
    ),
    "eod": Op(
        "eod", "EOD pipeline", ("eod",), writes=True,
        note="Full daily pipeline (monitor->fill->map->benchmarks->fx->recompute->validate).",
    ),
    "fx_load": Op(
        "fx_load", "FX load (fill)", ("fx", "load"), writes=True,
        note="Fill missing FX rates since the last observation.",
    ),
    "load_fill": Op(
        "load_fill", "Price load (fill)", ("load", "--scope"), writes=True,
        takes_scope=True,
        note="Gap-aware price fill for a universe scope (e.g. universe:ibov).",
    ),
}


def _advisory_key(op: str, args: list[str]) -> int:
    """Stable 63-bit advisory-lock key from op+args (Postgres bigint).

    hashlib, not ``hash()`` — Python's ``hash()`` is salted per process (PYTHONHASHSEED),
    so two processes would compute different keys for the same op and the cross-process
    lock would guard nothing.
    """
    digest = hashlib.sha256("\x00".join([op, *args]).encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_job(job_id: int, op: Op, args: list[str]) -> None:
    """Worker body (daemon thread): hold an advisory lock, run the subprocess, record result."""
    try:
        conn = connect()  # qrp.job ledger lives in the qrp database
    except Exception:  # noqa: BLE001 — can't reach the ledger, so can't mark the row failed;
        return  # the busy-check's staleness window unwedges the orphaned 'queued' row
    conn.autocommit = True
    key = _advisory_key(op.key, args)
    proc: subprocess.Popen | None = None
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
            # Provenance: sym stamps pipeline_run_log.triggered_by from this env
            # var, correlating the qrp job with the sym run(s) it caused (O.2).
            env = {**os.environ, "SYM_TRIGGERED_BY": f"qrp-job:{job_id}"}
            try:
                # Popen + poll (not subprocess.run): the supervisor must HEARTBEAT
                # while the child runs — a dead supervisor then reads as a stale
                # beat (-> orphaned), not as 'running' forever (ADR-5's heartbeat).
                # encoding/errors pinned: text=True alone decodes with cp1252 on
                # Windows, and ONE undecodable byte would kill the drain thread,
                # fill the pipe, and deadlock the child until the timeout kill.
                proc = subprocess.Popen(
                    argv,
                    cwd=None,  # sym is a workspace member; `uv run sym` resolves from the qrp env
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
            except FileNotFoundError as exc:
                conn.execute(
                    "UPDATE qrp.job SET status='failed', error=%s, finished_at=%s WHERE job_id=%s",
                    (f"could not launch op: {exc}", _now(), job_id),
                )
                return
            # Drain stdout on a side thread — an unread PIPE fills and deadlocks
            # a chatty child; the poll loop below must never block on output.
            chunks: list[str] = []

            def _drain() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    chunks.append(line)

            reader = threading.Thread(target=_drain, daemon=True)
            reader.start()

            def _tail() -> str:
                reader.join(timeout=5)
                text = "".join(chunks)[-_OUTPUT_TAIL:]
                if reader.is_alive():
                    text += "\n[output truncated: drain incomplete]"
                return text

            deadline = time.monotonic() + _TIMEOUT_S
            while True:
                try:
                    # Server-time stamp (now() in SQL): the beat is COMPARED
                    # against server now() by the orphan window — a client clock
                    # skew must not eat the margin. Best-effort: a DB hiccup on
                    # one beat must not abandon a healthy child.
                    conn.execute(
                        "UPDATE qrp.job SET heartbeat_at = now() WHERE job_id=%s", (job_id,)
                    )
                except psycopg.Error:
                    pass
                returncode = proc.poll()
                if returncode is not None:
                    break
                if time.monotonic() > deadline:
                    _kill_tree(proc)
                    conn.execute(
                        "UPDATE qrp.job SET status='failed', error=%s, output=%s, "
                        "finished_at=%s WHERE job_id=%s",
                        (f"op timed out after {_TIMEOUT_S}s", _tail(), _now(), job_id),
                    )
                    return
                time.sleep(_BEAT_S)
            tail = _tail()
            status = "success" if returncode == 0 else "failed"
            conn.execute(
                "UPDATE qrp.job SET status=%s, exit_code=%s, output=%s, finished_at=%s "
                "WHERE job_id=%s",
                (status, returncode, tail, _now(), job_id),
            )
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
    except Exception as exc:  # noqa: BLE001 — never let a worker die silently
        # A fatal supervisor error must not leave a live child writing to the
        # warehouse behind a failed/orphaned row — kill the tree first.
        if proc is not None and proc.poll() is None:
            try:
                _kill_tree(proc)
            except Exception:  # noqa: BLE001
                pass
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
