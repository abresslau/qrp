"""API entrypoint — app factory mounting only the entitled module routers."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler as _default_http_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

from qrp_api.config import enabled_modules, modules, platform_config, platform_name

# ONE origin list for both the CORS middleware and the actuation guard (Story
# O.3) — drift between two lists recreates the misconfiguration class the
# guard exists to close. Env-overridable because Next auto-bumps the console
# to :3001 when :3000 is busy — without an override every console mutation
# would 403 with no recourse.
ALLOWED_ORIGINS: tuple[str, ...] = tuple(
    origin.strip()
    for origin in os.environ.get(
        "QRP_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
)

# Hostnames this API will answer for (DNS-rebinding companion to the origin
# guard): a rebound hostname resolving to 127.0.0.1 serves a page that is
# SAME-origin from the browser's view — the Host check refuses it regardless.
# "testserver" is starlette's TestClient default base host.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Error-type vocabulary (architecture §Format Patterns): the envelope's `type`
# derives from the honest HTTP status — routers keep raising plain
# HTTPException(status, detail) and the handlers translate.
_ERROR_TYPES = {
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation",
    500: "internal",
    503: "unavailable",
}


def _error_type_for(status_code: int) -> str:
    return _ERROR_TYPES.get(status_code, "internal" if status_code >= 500 else "error")


def _error_body(status_code: int, message: str, detail: object = None) -> dict:
    """The spec'd envelope `{error: {type, message, detail?}}` + legacy mirror.

    Top-level `detail` is KEPT alongside the envelope — the console reads it
    today; removing it is a breaking change for zero gain until the console
    fully migrates.
    """
    error: dict = {"type": _error_type_for(status_code), "message": message}
    if detail is not None:
        error["detail"] = detail
    # The mirror carries the STRUCTURED detail when one exists — for framework
    # 422s this is byte-compatible with FastAPI's original contract (the errors
    # array in top-level detail), which also keeps the committed generated TS
    # HTTPValidationError type correct.
    return {"error": error, "detail": detail if detail is not None else message}


def _error_response(status_code: int, message: str, detail: object = None) -> JSONResponse:
    return JSONResponse(status_code=status_code,
                        content=_error_body(status_code, message, detail))


class HealthResponse(BaseModel):
    status: str
    platform: str
    modules: list[str]


class ModuleInfo(BaseModel):
    key: str
    name: str | None = None
    description: str | None = None
    enabled: bool = False


class PlatformResponse(BaseModel):
    name: str
    tagline: str | None
    theme: str
    modules: list[ModuleInfo]


def _use_route_names_as_operation_ids(app: FastAPI) -> None:
    """Architecture typed-seam rule: explicit, unique ``operation_id`` on every route.

    Function names become the OpenAPI operation ids (so the generated TS client gets stable,
    human names); a duplicate function name across routers fails fast here instead of
    producing ambiguous generated types.
    """
    seen: dict[str, str] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            if route.name in seen:
                raise RuntimeError(
                    f"duplicate operation_id {route.name!r}: {seen[route.name]} and {route.path}"
                )
            seen[route.name] = route.path
            route.operation_id = route.name


def create_app() -> FastAPI:
    cfg = platform_config()
    name = platform_name()
    app = FastAPI(title=f"{name} API", version="0.1.0")

    # Middleware REGISTRATION ORDER IS LOAD-BEARING: Starlette runs the
    # LAST-registered middleware OUTERMOST. TrustedHost and CORS register
    # first; the origin guard registers last and therefore runs FIRST — a
    # foreign-origin actuation is refused before CORS or anything else sees it.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    # Dev: the Next.js console proxies /api/* (same-origin); these origins cover direct calls.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def actuation_origin_guard(request: Request, call_next):
        """Refuse mutating requests carrying a FOREIGN Origin (Story O.3, D4).

        Browsers attach Origin to every cross-site (and same-site POST)
        request, so a malicious page driving-by localhost actuation arrives
        WITH a foreign Origin — refused here before any route logic (the
        guard runs PRE-ROUTING: even nonexistent paths 403). Headless clients
        (curl, schedulers) send no Origin and pass: the guard targets
        browser-ambient CSRF, not API access. CORS preflights are OPTIONS and
        therefore untouched. Defense-in-depth alongside CORS: JSON bodies
        force a preflight today, but that protection is one content-type or
        config change away from gone — this check is explicit and structural.

        Recorded decisions (deny-by-design, not by accident):
        * ``Origin: null`` (sandboxed iframes, file:// pages, opaque origins)
          is FOREIGN — denied by the membership check.
        * An empty-string Origin is present-but-foreign — denied (fail-closed).
        * No Referer fallback for Origin-less requests — allow-on-absent is
          the accepted localhost posture; a token scheme has no session to
          bind to here.
        * This middleware covers the HTTP scope only. No WebSocket routes
          exist; a future WS actuation endpoint needs its own origin check
          (cross-site WebSocket hijacking sends no preflight at all).
        """
        if (
            request.method in _MUTATING
            and (origin := request.headers.get("origin")) is not None
            and origin not in ALLOWED_ORIGINS
        ):
            # Envelope built inline via the SHARED helper: this middleware runs
            # OUTSIDE the app's exception layer (outermost), so raising
            # HTTPException here would 500 instead of reaching the handlers.
            # Truncated echo: the header is attacker-controlled input.
            return _error_response(
                403, f"origin {origin[:100]!r} may not actuate this API"
            )
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_envelope(request: Request, exc: StarletteHTTPException):
        # Routers keep raising HTTPException(status, detail) — translated here
        # into the spec'd envelope; the status code is NEVER re-coded and the
        # exception's HEADERS are forwarded (Allow on 405, WWW-Authenticate on
        # a future 401 — RFC semantics the default handler preserves).
        if exc.status_code < 400:
            # An exotic 3xx HTTPException is a redirect — enveloping it would
            # lose Location; defer to the framework default.
            return await _default_http_handler(request, exc)
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        detail = None if isinstance(exc.detail, str) else exc.detail
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.status_code, message, detail),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_envelope(request: Request, exc: RequestValidationError):
        # jsonable_encoder: Pydantic v2 error ctx values can be raw objects —
        # without it a 422 would die as a serialization 500.
        return _error_response(
            422, "request validation failed", detail=jsonable_encoder(exc.errors())
        )

    @app.exception_handler(Exception)
    async def unhandled_envelope(request: Request, exc: Exception):
        # NEVER leak a traceback: class name only. Starlette's
        # ServerErrorMiddleware RE-RAISES after this handler returns (the
        # response still reaches the client), so uvicorn logs the full
        # traceback itself — printing here would double-log.
        headers = {}
        origin = request.headers.get("origin")
        if origin in ALLOWED_ORIGINS:
            # ServerErrorMiddleware sits OUTSIDE CORSMiddleware: without this
            # a direct-origin browser call could not READ the 500 envelope.
            headers["access-control-allow-origin"] = origin
        return JSONResponse(
            status_code=500,
            content=_error_body(
                500, f"internal error ({type(exc).__name__}) — see the API log"
            ),
            headers=headers,
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> dict:
        return {"status": "ok", "platform": name, "modules": [m["key"] for m in enabled_modules()]}

    @app.get("/api/platform", response_model=PlatformResponse)
    def platform() -> dict:
        meta = cfg.get("platform", {})
        return {
            "name": name,
            "tagline": meta.get("tagline"),
            "theme": meta.get("theme", "dark"),
            "modules": modules(),
        }

    enabled = {m["key"] for m in enabled_modules()}
    if "sym" in enabled:
        from qrp_api.modules.sym.router import router as sym_router

        app.include_router(sym_router)
    if "portfolios" in enabled:
        from portfolios.router import router as portfolios_router

        app.include_router(portfolios_router)
    if "analytics" in enabled:
        from analytics.router import router as analytics_router

        app.include_router(analytics_router)
    if "sym" in enabled:  # Operate is sym's control plane (trigger sym's own ops)
        from operate.router import router as operate_router

        app.include_router(operate_router)
    if "macro" in enabled:
        from macro.router import router as macro_router  # standalone package (carved out)

        app.include_router(macro_router)
    if "rates" in enabled:
        from rates.router import router as rates_router  # standalone package (fixed-income curves)

        app.include_router(rates_router)
    if "commodities" in enabled:
        from commodities.router import router as commodities_router  # standalone package

        app.include_router(commodities_router)
    if "signals" in enabled:
        from signals.router import router as signals_router

        app.include_router(signals_router)
    if "backtest" in enabled:
        from backtest.router import router as backtest_router

        app.include_router(backtest_router)
    if "optimiser" in enabled:
        from optimiser.router import router as optimiser_router

        app.include_router(optimiser_router)
    if "altdata" in enabled:
        from altdata.router import router as altdata_router

        app.include_router(altdata_router)
    if "lineage" in enabled:  # gateway-resident; lazy-imports lineage.* (dagster) inside handlers
        from qrp_api.modules.lineage.router import router as lineage_router

        app.include_router(lineage_router)
    if "data-monitor" in enabled:  # gateway-resident; aggregates per-package freshness + runs
        from qrp_api.modules.data_monitor.router import router as data_monitor_router

        app.include_router(data_monitor_router)

    _use_route_names_as_operation_ids(app)
    return app


app = create_app()
