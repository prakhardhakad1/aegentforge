"""Aggregates all /api route modules into one router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, integrations, missions, runs, templates, uploads

api_router = APIRouter(prefix="/api")
api_router.include_router(missions.router)
api_router.include_router(runs.router)
api_router.include_router(uploads.router)
api_router.include_router(templates.router)
api_router.include_router(integrations.router)

# /healthz intentionally lives outside /api (pinned route, no auth).
public_router = APIRouter()
public_router.include_router(health.router)

__all__ = ["api_router", "public_router"]
