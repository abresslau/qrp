"""Error envelope (Story O.4, chunk-1 D6). DB-free at the handler layer.

Every error path returns the spec'd `{error: {type, message, detail?}}` shape
with the legacy top-level `detail` mirror kept for console back-compat.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from qrp_api.main import ALLOWED_ORIGINS, create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()

    @app.get("/api/_test_boom")
    def _boom():
        raise RuntimeError("secret traceback content")

    return TestClient(app, raise_server_exceptions=False)


def _assert_envelope(resp, status: int, etype: str):
    assert resp.status_code == status
    body = resp.json()
    assert body["error"]["type"] == etype
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["detail"]  # legacy mirror for the console
    return body


def test_guard_403_carries_the_envelope(client):
    resp = client.post("/api/operate/run", json={"op": "validate"},
                       headers={"Origin": "https://evil.example"})
    body = _assert_envelope(resp, 403, "forbidden")
    assert "origin" in body["error"]["message"]


def test_router_http_exception_wrapped(client):
    # FastAPI's own 404 for an unknown path flows through the same handler.
    resp = client.get("/api/no/such/route")
    _assert_envelope(resp, 404, "not_found")


def test_framework_validation_error_wrapped(client):
    # Missing required body field -> RequestValidationError -> 422 envelope.
    resp = client.post("/api/operate/run", json={})
    body = _assert_envelope(resp, 422, "validation")
    assert body["error"]["detail"]  # the field-error structure rides inside


def test_route_422_detail_string_wrapped(client):
    # A router-raised HTTPException(422, "...") keeps its message.
    resp = client.post("/api/operate/run", json={"op": "nope"})
    body = _assert_envelope(resp, 422, "validation")
    assert "unknown op" in body["error"]["message"]


def test_unhandled_exception_is_500_envelope_without_traceback(client):
    resp = client.get("/api/_test_boom")
    body = _assert_envelope(resp, 500, "internal")
    assert "secret traceback content" not in resp.text
    assert "RuntimeError" in body["error"]["message"]  # class name only


def test_success_bodies_unwrapped(client):
    # Spec: success = the typed body directly, no envelope.
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert "error" not in resp.json()


def test_type_vocabulary_mapping():
    from qrp_api.main import _error_type_for

    assert _error_type_for(403) == "forbidden"
    assert _error_type_for(404) == "not_found"
    assert _error_type_for(409) == "conflict"
    assert _error_type_for(422) == "validation"
    assert _error_type_for(503) == "unavailable"
    assert _error_type_for(500) == "internal"
    assert _error_type_for(418) == "error"


def test_allowed_origins_import_still_used():
    assert ALLOWED_ORIGINS  # imported for parity with the guard tests
