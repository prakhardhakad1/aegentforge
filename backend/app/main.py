"""AgentForge FastAPI application.

Run from ``backend/`` (never from the repo root)::

    uvicorn app.main:app --reload

Import roots available with that cwd: ``app``, ``connectors``,
``integrations``, ``realtime`` (plus installed ``orchestrator`` /
``agentforge_tools`` packages).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router, public_router
from app.config import get_settings

logger = logging.getLogger("agentforge.main")


def configure_logging() -> None:
    """Idempotent stdlib logging setup."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )


OPENAPI_TAGS: list[dict[str, Any]] = [
    {
        "name": "Missions",
        "description": "Create and browse business missions (the user's one-sentence goal).",
    },
    {
        "name": "Runs",
        "description": (
            "Run lifecycle: start a run, poll its event log, fetch the full "
            "snapshot, or stream events live over WebSocket."
        ),
    },
    {
        "name": "Uploads",
        "description": "Upload and profile CSV business datasets.",
    },
    {
        "name": "Templates",
        "description": "Prebuilt agent-team templates (the template marketplace).",
    },
    {
        "name": "Integrations",
        "description": (
            "Export a finished run as an n8n workflow and download its report "
            "as Markdown/PDF. Endpoints return 501 while the owning agent's "
            "module is unavailable — success is never faked."
        ),
    },
    {
        "name": "Health",
        "description": "Liveness probe.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create schema + seed templates on startup; dispose the engine on shutdown."""
    from app.db.base import dispose_engine, init_db

    configure_logging()
    settings = get_settings()
    logger.info(
        "AgentForge starting (run_mode=%s llm_mode=%s auth=%s)",
        settings.run_mode,
        settings.llm_mode,
        "on" if settings.auth_enabled else "off (guest mode)",
    )
    init_db()
    try:
        yield
    finally:
        logger.info("AgentForge shutting down")
        dispose_engine()


def create_app() -> FastAPI:
    """Application factory: CORS, routers, exception handlers, OpenAPI tags."""
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="AgentForge API",
        version="1.0.0",
        description=(
            "Hire an AI team with one sentence. A mission spawns a planner and "
            "specialist agents (researcher, analyst, forecaster, critic) that "
            "stream progress live and deliver a structured report."
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    cors_origins = settings.cors_origin_list
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials="*" not in cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        del request
        detail = exc.detail if isinstance(exc.detail, str) else repr(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "status_code": exc.status_code, "detail": detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        # Strip exception instances from validator contexts so the body is
        # always JSON-serializable.
        errors = [
            {key: value for key, value in err.items() if key != "ctx"}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "status_code": 422, "detail": errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled error on %s %s: %s", request.method, request.url.path, exc
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "status_code": 500,
                "detail": "Internal server error",
            },
        )

    app.include_router(api_router)
    app.include_router(public_router)
    return app


app = create_app()
