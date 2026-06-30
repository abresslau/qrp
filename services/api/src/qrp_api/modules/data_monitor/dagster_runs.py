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

from qrp_api.config import dagster_code_location, dagster_repository


def graphql_url() -> str:
    return os.environ.get("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3333/graphql")


_LAUNCH_MUTATION = """
mutation Launch($selector: JobOrPipelineSelector!, $rc: RunConfigData) {
  launchRun(executionParams: {selector: $selector, runConfigData: $rc, mode: "default"}) {
    __typename
    ... on LaunchRunSuccess { run { runId status } }
    ... on RunConfigValidationInvalid { errors { message } }
    ... on PipelineNotFoundError { message }
    ... on InvalidSubsetError { message }
    ... on PythonError { message }
  }
}
"""


def launch_job(
    job: str, subcategories: list[str] | None = None, as_of_date: str | None = None,
    start_date: str | None = None, end_date: str | None = None,
    timeout: float = 8.0,
) -> dict:
    """Launch a bucket job in the running Dagster instance via GraphQL ``launchRun``.

    The bucket jobs wrap a single op whose config is the BucketConfig
    (``subcategories`` + the ``start_date``/``end_date`` window, or the ``as_of_date`` single-date
    alias) — so ``subcategories=["msci"]`` on ``index_levels`` runs only ``sym msci-pull``, and a
    ``start_date``/``end_date`` pair backfills that window. Returns ``{ok, run_id?, status?, error?}``;
    never raises (a dead daemon → ``{ok: False, error: …}``)."""
    cfg: dict = {}
    if subcategories is not None:
        cfg["subcategories"] = list(subcategories)
    if as_of_date:
        cfg["as_of_date"] = as_of_date
    if start_date:
        cfg["start_date"] = start_date
    if end_date:
        cfg["end_date"] = end_date
    run_config = {"ops": {f"{job}_load": {"config": cfg}}}
    selector = {
        "repositoryLocationName": dagster_code_location(),
        "repositoryName": dagster_repository(),
        "pipelineName": job,
    }
    payload = {"query": _LAUNCH_MUTATION, "variables": {"selector": selector, "rc": run_config}}
    try:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            graphql_url(), data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed local host
            data = json.load(resp)
        res = data["data"]["launchRun"]
    except Exception as exc:  # noqa: BLE001 — surface a clean error, never raise
        return {"ok": False, "error": f"Dagster not reachable ({type(exc).__name__})"}
    if res.get("__typename") == "LaunchRunSuccess":
        return {"ok": True, "run_id": res["run"]["runId"], "status": res["run"].get("status")}
    msg = res.get("message") or "; ".join(e.get("message", "") for e in res.get("errors", []))
    return {"ok": False, "error": f"{res.get('__typename')}: {msg or 'launch failed'}"}


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


def latest_runs_by_job(timeout: float = 1.0) -> tuple[bool, dict[str, dict]]:
    """``(reachable, {job_name: {status, started_at, finished_at, source:"dagster"}})`` — best effort.

    ``reachable`` is True iff the Dagster GraphQL endpoint answered (the daemon is up) — distinct
    from whether any runs exist yet (a fresh ``dagster dev`` is reachable with zero runs). On any
    failure (endpoint down, timeout, unexpected shape) returns ``(False, {})``. The short timeout
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
    except Exception:  # noqa: BLE001 — best-effort; any failure means "Dagster not reachable"
        return False, {}

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
    return True, latest
