"""SQLAlchemy ORM models for AgentForge.

All timestamps are stored as naive UTC datetimes (SQLite-friendly); the event
envelope carries its own ISO-8601 ``Z``-suffixed ``ts`` string per
docs/INTERFACES.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC now (SQLite stores naive datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    """Canonical string UUID for primary keys."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Declarative base for all AgentForge models."""


class User(Base):
    """A mission owner. v1 is single-tenant guest mode: one lightweight user
    row is created per mission so the concept exists for post-hackathon
    multi-user work."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    display_name: Mapped[str | None] = mapped_column(String(120), default="guest")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Dataset(Base):
    """An uploaded CSV dataset (bytes stored at ``path``)."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str | None] = mapped_column(String(255), default=None)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    columns_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    dtypes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    quality_notes_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    path: Mapped[str | None] = mapped_column(String(1024), default=None)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Mission(Base):
    """A business goal written by the user, optionally tied to a team template
    and an uploaded dataset."""

    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    goal: Mapped[str] = mapped_column(Text)
    template_id: Mapped[str | None] = mapped_column(String(64), default=None)
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id"), default=None
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Run(Base):
    """One execution of a mission by the agent team."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    mission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("missions.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")
    mode: Mapped[str | None] = mapped_column(String(8), default=None)  # demo | live
    template_id: Mapped[str | None] = mapped_column(String(64), default=None)
    plan_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON, default=None
    )
    token_usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    error_stage: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AgentStep(Base):
    """Persistent copy of every pinned event envelope for a run (the run's
    event log). Doubles as replay source when the in-memory broadcaster is
    empty (e.g. after a process restart)."""

    __tablename__ = "agent_steps"
    __table_args__ = (Index("ix_agent_steps_run_seq", "run_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(48))
    agent: Mapped[str | None] = mapped_column(String(24), default=None)
    subtask_id: Mapped[str | None] = mapped_column(String(64), default=None)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ts: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Artifact(Base):
    """A deliverable produced during a run (chart, table, report, ...)."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), index=True)
    subtask_id: Mapped[str | None] = mapped_column(String(64), default=None)
    kind: Mapped[str] = mapped_column(String(24))
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    path: Mapped[str | None] = mapped_column(String(1024), default=None)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Template(Base):
    """A prebuilt agent-team template (marketplace row). Seeded at startup
    from ``app.templates_data``."""

    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    tags_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    team_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    planner_prompt: Mapped[str] = mapped_column(Text)
    sample_mission: Mapped[str] = mapped_column(Text)
    expected_dag_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    report_outline_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
