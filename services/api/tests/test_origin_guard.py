"""Actuation origin guard (Story O.3, chunk-1 D4). DB-free at the guard layer.

A browser attaches Origin to every cross-site request; headless clients don't.
The guard refuses mutating methods with a FOREIGN Origin (403) before any
route logic runs — assertions therefore never need a database: a request that
gets PAST the guard may 4xx/5xx in the route, which is fine, as long as it is
not the guard's 403.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from qrp_api.main import ALLOWED_ORIGINS, create_app

client = TestClient(create_app(), raise_server_exceptions=False)

EVIL = {"Origin": "https://evil.example"}
HOME = {"Origin": ALLOWED_ORIGINS[0]}


def _is_guard_403(resp) -> bool:
    return resp.status_code == 403 and "origin" in resp.json().get("detail", "").lower()


def test_foreign_origin_post_is_refused():
    resp = client.post("/api/operate/run", json={"op": "validate"}, headers=EVIL)
    assert _is_guard_403(resp)


def test_foreign_origin_blocks_module_routes_structurally():
    # Coverage is app-wide middleware, not per-router opt-in: a portfolios
    # mutating route must be guarded too.
    resp = client.post("/api/portfolios", json={"name": "x"}, headers=EVIL)
    assert _is_guard_403(resp)


def test_allowed_origin_passes_the_guard():
    resp = client.post("/api/operate/run", json={"op": "nope"}, headers=HOME)
    assert not _is_guard_403(resp)   # reaches the route (422 unknown op / DB error)


def test_no_origin_headless_client_passes():
    resp = client.post("/api/operate/run", json={"op": "nope"})
    assert not _is_guard_403(resp)


def test_reads_unaffected_by_foreign_origin():
    resp = client.get("/api/health", headers=EVIL)
    assert resp.status_code == 200


def test_preflight_options_passes():
    resp = client.options(
        "/api/operate/run",
        headers={"Origin": ALLOWED_ORIGINS[0],
                 "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code in (200, 204)
