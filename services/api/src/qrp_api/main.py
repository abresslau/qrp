"""API entrypoint — app factory mounting only the entitled module routers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from qrp_api.config import enabled_modules, modules, platform_config, platform_name


def create_app() -> FastAPI:
    cfg = platform_config()
    name = platform_name()
    app = FastAPI(title=f"{name} API", version="0.1.0")

    # Dev: the Next.js console proxies /api/* (same-origin); these origins cover direct calls.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"platform": name, "modules": [m["key"] for m in enabled_modules()]}

    @app.get("/api/platform")
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
        from qrp_api.modules.portfolios.router import router as portfolios_router

        app.include_router(portfolios_router)
    if "analytics" in enabled:
        from qrp_api.modules.analytics.router import router as analytics_router

        app.include_router(analytics_router)
    if "sym" in enabled:  # Operate is sym's control plane (trigger sym's own ops)
        from qrp_api.modules.operate.router import router as operate_router

        app.include_router(operate_router)
    if "macro" in enabled:
        from qrp_api.modules.macro.router import router as macro_router

        app.include_router(macro_router)
    if "signal" in enabled:
        from qrp_api.modules.signal.router import router as signal_router

        app.include_router(signal_router)
    if "backtest" in enabled:
        from qrp_api.modules.backtest.router import router as backtest_router

        app.include_router(backtest_router)
    if "optimiser" in enabled:
        from qrp_api.modules.optimiser.router import router as optimiser_router

        app.include_router(optimiser_router)
    if "altdata" in enabled:
        from qrp_api.modules.altdata.router import router as altdata_router

        app.include_router(altdata_router)

    return app


app = create_app()
