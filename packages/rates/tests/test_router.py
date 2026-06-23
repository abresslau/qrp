"""Rates API surface — the router exposes the curve + derived-spread read routes."""

from __future__ import annotations

from rates.router import router

_PATHS = {r.path for r in router.routes}


def test_curve_routes_exist():
    assert "/api/rates/curve" in _PATHS
    assert "/api/rates/curve/series" in _PATHS


def test_spread_routes_exist():
    assert "/api/rates/spreads" in _PATHS
    assert "/api/rates/spread/{key}" in _PATHS


def test_curve_movie_route_exists():
    assert "/api/rates/curve/movie" in _PATHS
