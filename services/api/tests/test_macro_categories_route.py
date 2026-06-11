"""Macro categories route (Story C.1). DB-free — route-table assertions only."""

from __future__ import annotations

import qrp_api.main as main_mod
from qrp_api.main import create_app


def _route_paths(app=None) -> set[str]:
    app = app or create_app()
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_macro_categories_route_exists():
    paths = _route_paths()
    assert "/api/macro/categories" in paths
    assert "/api/macro/series" in paths  # unchanged neighbours still mounted
    assert "/api/macro/series/{series_id}" in paths or any(
        p.startswith("/api/macro/series/{series_id") for p in paths
    )


def test_macro_toggle_off_removes_categories_route(monkeypatch):
    import qrp_api.config as config_mod  # noqa: F401 (parallel to the A.1 pattern)

    real = main_mod.enabled_modules()
    without = [m for m in real if m["key"] != "macro"]
    monkeypatch.setattr(main_mod, "enabled_modules", lambda: without)
    paths = _route_paths(main_mod.create_app())
    assert not {p for p in paths if p.startswith("/api/macro")}
