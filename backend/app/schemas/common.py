"""Shared / envelope schemas (event envelope, health, error)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Exact event-type strings pinned in docs/INTERFACES.md.
EVENT_TYPES: tuple[str, ...] = (
    "run_started",
    "plan_created",
    "agent_started",
    "thought_summary",
    "tool_call",
    "tool_result",
    "artifact_created",
    "step_completed",
    "agent_finished",
    "run_finished",
    "run_failed",
    "token_update",
)

# Exact agent-role strings pinned in docs/INTERFACES.md.
AGENT_ROLES: tuple[str, ...] = ("planner", "researcher", "analyst", "forecaster", "critic")

# Exact artifact-kind strings pinned in docs/INTERFACES.md.
ARTIFACT_KINDS: tuple[str, ...] = (
    "chart",
    "table",
    "text",
    "prediction",
    "recommendation",
    "report_markdown",
    "report_pdf",
    "file",
)

RUN_STATUSES: tuple[str, ...] = ("queued", "running", "succeeded", "failed", "partial")


class EventOut(BaseModel):
    """The canonical pinned event envelope (WS + DB + polling)."""

    model_config = {"extra": "allow"}

    type: str
    run_id: str
    seq: int = Field(ge=1)
    ts: str
    agent: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EventsResponse(BaseModel):
    """Response of GET /api/runs/{id}/events."""

    events: list[EventOut] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Response of GET /healthz."""

    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    """JSON error body shape used by the app-wide exception handlers."""

    error: str
    status_code: int
    detail: Any = None
