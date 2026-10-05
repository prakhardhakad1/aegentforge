"""Run schemas: Run, snapshot, artifacts, token usage."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import EventOut
from app.schemas.mission import MissionRead


class RunCreate(BaseModel):
    """POST /api/missions/{id}/runs request body (may be omitted entirely)."""

    template_id: Optional[str] = Field(default=None, max_length=64)


class RunRead(BaseModel):
    """Pinned Run shape: {id, mission_id, status, created_at, finished_at?}
    plus useful extra fields (mode, error) — pinned fields always present."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    status: Literal["queued", "running", "succeeded", "failed", "partial"]
    created_at: datetime
    finished_at: Optional[datetime] = None
    mode: Optional[str] = None
    template_id: Optional[str] = None
    error: Optional[str] = None
    error_stage: Optional[str] = None


class ArtifactOut(BaseModel):
    """Artifact row exposed in the run snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    subtask_id: Optional[str] = None
    kind: str
    name: Optional[str] = None
    summary: Optional[str] = None
    path: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


def _default_token_usage() -> dict[str, Any]:
    return {
        "per_agent": {},
        "totals": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }


class TokenUsage(BaseModel):
    """Canonical token/cost meter shape (per docs/INTERFACES.md RunResult)."""

    per_agent: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=lambda: _default_token_usage()["totals"])


class RunSnapshot(BaseModel):
    """GET /api/runs/{id} response — also the input shape for n8n export.

    ``report`` is the canonical report dict produced by orchestrator.report
    (or demo mode); it is passed through unvalidated because it crosses an
    agent boundary — see NOTES.md.
    """

    run: RunRead
    mission: MissionRead
    events: list[EventOut] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    token_usage: dict[str, Any] = Field(default_factory=_default_token_usage)
    report: Optional[dict[str, Any]] = None
