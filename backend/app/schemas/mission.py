"""Mission schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MissionCreate(BaseModel):
    """POST /api/missions request body."""

    goal: str = Field(min_length=1, max_length=8000, description="The business goal")
    template_id: Optional[str] = Field(default=None, max_length=64)
    dataset_id: Optional[str] = Field(default=None, max_length=36)

    @field_validator("goal")
    @classmethod
    def _goal_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be blank")
        return value.strip()

    @field_validator("template_id", "dataset_id")
    @classmethod
    def _strip_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class MissionRead(BaseModel):
    """Pinned Mission shape: {id, goal, template_id?, dataset_id?, created_at}."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    goal: str
    template_id: Optional[str] = None
    dataset_id: Optional[str] = None
    created_at: datetime


class MissionListResponse(BaseModel):
    """Response of GET /api/missions (?limit&offset)."""

    missions: list[MissionRead] = Field(default_factory=list)
    total: int
