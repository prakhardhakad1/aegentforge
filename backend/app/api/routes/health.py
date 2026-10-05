"""Health route: GET /healthz (no auth, no /api prefix)."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.schemas.common import HealthResponse

logger = logging.getLogger("agentforge.health")

router = APIRouter(tags=["Health"])


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns {\"status\": \"ok\"} when the API process is up.",
)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")
