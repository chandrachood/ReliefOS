from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.integrations import MediaService, build_queue_publisher
from app.repositories import ConflictError, build_repository
from app.services import ReliefOSService
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        logging.basicConfig(
            level=configured.log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        repository = build_repository(configured)
        media = MediaService(configured)
        app.state.settings = configured
        app.state.repository = repository
        app.state.service = ReliefOSService(
            repository=repository,
            queue=build_queue_publisher(configured),
            media=media,
            settings=configured,
        )
        yield

    app = FastAPI(
        title=configured.app_name,
        version="0.1.0",
        description=(
            "Open-source disaster reporting and human-controlled rescue coordination. "
            "AI recommendations never replace emergency-command authority."
        ),
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
            "script-src 'self' https://unpkg.com; style-src 'self' https://unpkg.com; "
            "img-src 'self' data: https://*.tile.openstreetmap.org; connect-src 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
        if configured.app_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready() -> dict[str, str]:
        return {"status": "ready", "storage": configured.storage_backend}

    @app.exception_handler(ConflictError)
    async def conflict_handler(_request, exc: ConflictError):  # type: ignore[no-untyped-def]
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    web_directory = Path(__file__).resolve().parent.parent / "web"
    if web_directory.exists():
        app.mount("/portal", StaticFiles(directory=web_directory, html=True), name="portal")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/portal/")

    return app


app = create_app()
