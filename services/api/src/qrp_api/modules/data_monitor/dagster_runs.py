"""Best-effort latest-Dagster-run lookup for the EOD monitor.

The lineage code location runs as a SEPARATE process (``dagster dev -m lineage.definitions``), not
inside this API. When its GraphQL endpoint is reachable we surface each bucket job's most-recent
run; when it isn't (the daemon isn't running), every lookup degrades to ``None`` — the EOD page
still renders its freshness rows. NEVER raises.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime


def graphql_url() -> str:
    return os.environ.get("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")


# Last 50 runs across all jobs (one request); we group to the latest per job name client-side.
# ``pipelineName`` is the job name on a run in Dagster's GraphQL schema.
_QUERY = (
    "{ runsOrError(limit: 50) { __typename "
    "... on Runs { results { status startTime endTime pipelineName } } } }"
)


def _iso(epoch: float | None) -> str | None:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=UTC).isoformat()
    except (ValueError, OSError, TypeError):
        return None


def latest_runs_by_job(timeout: float = 1.0) -> dict[str, dict]:
    """``{job_name: {status, started_at, finished_at, source:"dagster"}}`` — best effort.

    Returns ``{}`` on any failure (endpoint down, timeout, unexpected shape). The short timeout
    keeps the EOD endpoint snappy when the daemon isn't running.
    """
    try:
        body = json.dumps({"query": _QUERY}).encode()
        req = urllib.request.Request(
            graphql_url(), data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed local host
            payload = json.load(resp)
        results = payload["data"]["runsOrError"]["results"]
    except Exception:  # noqa: BLE001 — best-effort; any failure means "no run info available"
        return {}

    latest: dict[str, dict] = {}
    for r in results or []:
        job = r.get("pipelineName")
        if not job:
            continue
        st = r.get("startTime") or 0
        prev = latest.get(job)
        if prev is None or st > prev["_st"]:
            latest[job] = {
                "status": r.get("status"),
                "started_at": _iso(r.get("startTime")),
                "finished_at": _iso(r.get("endTime")),
                "source": "dagster",
                "_st": st,
            }
    for v in latest.values():
        v.pop("_st", None)
    return latest
