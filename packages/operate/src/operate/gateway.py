"""DB gateway for the Operate job ledger (QRP-own `qrp.job`) + sym run history."""

from __future__ import annotations

import json
import re

import psycopg

from operate.executor import OPS, launch

# Load scopes runnable through the API: universe scopes only (the CLI accepts
# more; the API allowlist stays narrow until something needs widening).
_SCOPE_RE = re.compile(r"^universe:[a-z0-9_-]+$")


class DbOperateGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self._conn.autocommit = True

    def ops(self) -> list[dict]:
        return [
            {
                "key": o.key,
                "label": o.label,
                "writes": o.writes,
                "takes_universe": o.takes_universe,
                "takes_scope": o.takes_scope,
                "note": o.note,
            }
            for o in OPS.values()
        ]

    def _row(self, r: tuple) -> dict:
        (jid, op, args, status, exit_code, output, error,
         created, started, finished, heartbeat) = r
        return {
            "job_id": jid,
            "op": op,
            "args": list(args or []),
            "status": status,
            "exit_code": exit_code,
            "output": output,
            "error": error,
            "created_at": created.isoformat() if created else None,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "heartbeat_at": heartbeat.isoformat() if heartbeat else None,
        }

    # 'running' with a stale beat (3x the executor's 10s cadence) reads as
    # ORPHANED: the supervising process died. Read-time reclassification is
    # sufficient — Postgres frees advisory locks on disconnect, so the dead
    # run's lock is already gone and nothing needs a reaper.
    _COLS = (
        "job_id, op, args, "
        "CASE WHEN status = 'running' "
        "      AND coalesce(heartbeat_at, started_at, created_at) "
        "          < now() - interval '30 seconds' "
        "     THEN 'orphaned' ELSE status END AS status, "
        "exit_code, output, error, created_at, started_at, finished_at, heartbeat_at"
    )

    def list(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM qrp.job ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, job_id: int) -> dict | None:
        r = self._conn.execute(
            f"SELECT {self._COLS} FROM qrp.job WHERE job_id = %s", (job_id,)
        ).fetchone()
        return self._row(r) if r else None

    def run(self, op_key: str, args: list[str], confirm: bool) -> dict:
        """Validate against the allowlist, guard, insert a job row, and launch the worker.

        Returns {ok, job_id?, status, reason?}. Writers require confirm=True. A second run
        of the same op+args while one is queued/running is rejected synchronously.
        """
        op = OPS.get(op_key)
        if op is None:
            return {"ok": False, "status": "rejected", "reason": f"unknown op {op_key!r}"}
        if any(a.startswith("-") for a in args):
            # args ride straight onto the sym CLI argv; flag-like values would let a caller
            # inject arbitrary options (e.g. mode switches) past the allowlist.
            return {"ok": False, "status": "rejected", "reason": "flag-like args are not allowed"}
        if op.takes_universe and not args:
            return {"ok": False, "status": "rejected", "reason": "this op requires a universe id"}
        if op.takes_scope and (len(args) != 1 or not _SCOPE_RE.match(args[0])):
            return {
                "ok": False,
                "status": "rejected",
                "reason": "this op requires exactly one scope arg shaped universe:<id>",
            }
        if op.writes and not confirm:
            return {
                "ok": False,
                "status": "rejected",
                "reason": f"{op.label} writes sym data — re-run with confirm=true",
            }
        # Busy = a live duplicate: queued within the 2h window (covers a launch
        # thread that never started), or running with a FRESH heartbeat. A stale
        # beat means the supervisor died — and its advisory lock died with the
        # connection, so blocking on the row would be artificial (O.2).
        busy = self._conn.execute(
            "SELECT count(*) FROM qrp.job WHERE op = %s AND args = %s::jsonb "
            "AND ((status = 'queued' AND created_at > now() - interval '2 hours') "
            "  OR (status = 'running' "
            "      AND coalesce(heartbeat_at, started_at, created_at) "
            "          > now() - interval '30 seconds'))",
            (op_key, json.dumps(args)),
        ).fetchone()[0]
        if busy:
            return {"ok": False, "status": "conflict", "reason": "an identical run is in progress"}

        job_id = self._conn.execute(
            "INSERT INTO qrp.job (op, args, status) VALUES (%s, %s::jsonb, 'queued') "
            "RETURNING job_id",
            (op_key, json.dumps(args)),
        ).fetchone()[0]
        launch(int(job_id), op, args)
        return {"ok": True, "job_id": int(job_id), "status": "queued", "reason": None}


def run_history(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    """Recent sym `pipeline_run_log` rows (FR-6) — read-only against the sym DB.

    sym's run log is the system-of-record for what an op DID; `triggered_by`
    (qrp-job:<id> or NULL for manual CLI runs) correlates it with `qrp.job`.
    """
    rows = conn.execute(
        """
        SELECT run_id, mode, source, started_at, finished_at, attempted, loaded,
               skipped, errored, rows_written, status, triggered_by
          FROM pipeline_run_log
         ORDER BY run_id DESC
         LIMIT %s
        """,
        (limit,),
    ).fetchall()
    cols = ["run_id", "mode", "source", "started_at", "finished_at", "attempted",
            "loaded", "skipped", "errored", "rows_written", "status", "triggered_by"]
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        d["started_at"] = d["started_at"].isoformat() if d["started_at"] else None
        d["finished_at"] = d["finished_at"].isoformat() if d["finished_at"] else None
        out.append(d)
    return out
