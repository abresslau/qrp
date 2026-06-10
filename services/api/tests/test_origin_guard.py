"""Actuation origin guard + trusted hosts (Story O.3, chunk-1 D4). DB-free.

A browser attaches Origin to every cross-site request; headless clients don't.
The guard refuses mutating methods with a FOREIGN Origin (403) PRE-ROUTING —
assertions never need a database: a request past the guard may 4xx in the
route (the deterministic 422 for an unknown op), which is asserted explicitly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from qrp_api.main import ALLOWED_ORIGINS, create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


EVIL = {"Origin": "https://evil.example"}
HOME = {"Origin": ALLOWED_ORIGINS[0]}


def _is_guard_403(resp) -> bool:
    return resp.status_code == 403 and "origin" in resp.json().get("detail", "").lower()


def test_foreign_origin_post_is_refused(client):
    resp = client.post("/api/operate/run", json={"op": "validate"}, headers=EVIL)
    assert _is_guard_403(resp)


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_all_mutating_verbs_are_guarded(client, method):
    resp = getattr(client, method)("/api/portfolios/1", headers=EVIL)
    assert _is_guard_403(resp)


def test_guard_runs_pre_routing(client):
    # THE structural property: the middleware fires before routing, so even a
    # nonexistent path 403s — coverage cannot depend on which routers mount.
    resp = client.post("/no/such/route", headers=EVIL)
    assert _is_guard_403(resp)


def test_null_origin_is_foreign_by_design(client):
    # Sandboxed iframes / file:// pages send the literal value 'null' — an
    # opaque origin is foreign, denied by design (documented in the guard).
    resp = client.post("/api/operate/run", json={"op": "validate"},
                       headers={"Origin": "null"})
    assert _is_guard_403(resp)


def test_empty_origin_fails_closed(client):
    resp = client.post("/api/operate/run", json={"op": "validate"},
                       headers={"Origin": ""})
    assert _is_guard_403(resp)


def test_allowed_origin_reaches_the_route(client):
    # 422 'unknown op' is deterministic and DB-free — proves the request got
    # PAST the guard and into route logic (not merely "wasn't a guard 403").
    resp = client.post("/api/operate/run", json={"op": "nope"}, headers=HOME)
    assert resp.status_code == 422
    assert "unknown op" in resp.json()["detail"]


def test_no_origin_headless_client_reaches_the_route(client):
    resp = client.post("/api/operate/run", json={"op": "nope"})
    assert resp.status_code == 422


def test_reads_unaffected_by_foreign_origin(client):
    resp = client.get("/api/health", headers=EVIL)
    assert resp.status_code == 200


def test_preflight_options_passes(client):
    resp = client.options(
        "/api/operate/run",
        headers={"Origin": ALLOWED_ORIGINS[0],
                 "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code in (200, 204)


def test_foreign_host_is_refused(client):
    # DNS-rebinding companion: a rebound hostname resolving to 127.0.0.1 is
    # refused by the Host check even though the browser sees it as same-origin.
    resp = client.get("/api/health", headers={"Host": "rebound.evil.example"})
    assert resp.status_code == 400


def test_long_origin_echo_is_truncated(client):
    resp = client.post("/api/operate/run", json={"op": "validate"},
                       headers={"Origin": "https://" + "a" * 500 + ".example"})
    assert resp.status_code == 403
    assert len(resp.json()["detail"]) < 200
