"""Upload schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """POST /api/upload response (pinned shape)."""

    id: str
    filename: str
    row_count: int
    columns: list[str] = Field(default_factory=list)
    dtypes: dict[str, str] = Field(default_factory=dict)
    preview: list[list[Any]] = Field(default_factory=list)
    quality_notes: list[str] = Field(default_factory=list)
