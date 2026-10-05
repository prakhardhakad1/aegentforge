"""Template schemas (marketplace)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class TeamMember(BaseModel):
    """One specialist in the template's team."""

    role: str
    title: str
    system_prompt: str


class DagNode(BaseModel):
    """One node of the template's expected DAG."""

    id: str
    title: str
    agent: str
    depends_on: List[str] = Field(default_factory=list)


class TemplateRead(BaseModel):
    """Pinned Template shape."""

    id: str
    name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    team: List[TeamMember] = Field(default_factory=list)
    planner_prompt: str
    sample_mission: str
    expected_dag: List[DagNode] = Field(default_factory=list)
    report_outline: List[str] = Field(default_factory=list)


class TemplateListResponse(BaseModel):
    """Response of GET /api/templates."""

    templates: List[TemplateRead] = Field(default_factory=list)


def template_dict_to_read(spec: dict) -> TemplateRead:
    """Build a TemplateRead from a template dict (DB row or in-code spec)."""
    return TemplateRead(
        id=spec["id"],
        name=spec.get("name", ""),
        description=spec.get("description", ""),
        tags=list(spec.get("tags", []) or []),
        team=[
            TeamMember(
                role=member.get("role", ""),
                title=member.get("title", ""),
                system_prompt=member.get("system_prompt", ""),
            )
            for member in (spec.get("team", []) or [])
        ],
        planner_prompt=spec.get("planner_prompt", ""),
        sample_mission=spec.get("sample_mission", ""),
        expected_dag=[
            DagNode(
                id=node.get("id", ""),
                title=node.get("title", ""),
                agent=node.get("agent", ""),
                depends_on=list(node.get("depends_on", []) or []),
            )
            for node in (spec.get("expected_dag", []) or [])
        ],
        report_outline=list(spec.get("report_outline", []) or []),
    )


def template_row_to_dict(row) -> dict:
    """Convert a ``models.Template`` row to the plain template dict shape."""
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tags": list(row.tags_json or []),
        "team": list(row.team_json or []),
        "planner_prompt": row.planner_prompt,
        "sample_mission": row.sample_mission,
        "expected_dag": list(row.expected_dag_json or []),
        "report_outline": list(row.report_outline_json or []),
    }


__all__ = [
    "DagNode",
    "TeamMember",
    "TemplateListResponse",
    "TemplateRead",
    "template_dict_to_read",
    "template_row_to_dict",
]
