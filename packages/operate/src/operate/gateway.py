"""DB gateway for the Operate job ledger (QRP-own `qrp.job`)."""

from __future__ import annotations

import json

import psycopg

from operate.executor import OPS, launch


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
                "note": o.note,
            }
            for o in OPS.values()
        ]

    def _row(self, r: tuple) -> dict:
        (jid, op, args, status, exit_code, output, error, created, started, finished) = r
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
        }

    _COLS = (
        "job_id, op, args, status, exit_code, output, error, created_at, started_at, finished_at"
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
        if op.writes and not confirm:
            return {
                "ok": False,
                "status": "rejected",
                "reason": f"{op.label} writes sym data — re-run with confirm=true",
            }
        # The 2-hour staleness window unwedges rows orphaned by a process crash (daemon threads
        # die with the API): an op killed mid-run stops blocking re-runs once the window passes.
        # Generous vs the executor's 1800s subprocess timeout.
        busy = self._conn.execute(
            "SELECT count(*) FROM qrp.job WHERE op = %s AND args = %s::jsonb "
            "AND status IN ('queued', 'running') "
            "AND created_at > now() - interval '2 hours'",
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
