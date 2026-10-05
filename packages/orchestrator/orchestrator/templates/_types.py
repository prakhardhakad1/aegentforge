"""orchestrator.templates._types — pinned Template typing (Agent 8).

TypedDict views over the pinned ``Template`` shape from ``docs/INTERFACES.md``.
Runtime values are plain, JSON-serializable dicts — the pinned shape IS a JSON
contract consumed by the backend's ``GET /api/templates``, so every marketplace
template in this subpackage is stored as a plain dict and these classes exist
purely for typing and documentation. Nothing here imports the orchestrator
core; this subpackage's only runtime dependency is the standard library.
"""

from __future__ import annotations

from typing import TypedDict

__all__ = ["TeamMember", "DagNode", "TemplateDict"]


class TeamMember(TypedDict):
    """One specialist on a template's team (pinned keys, exactly these).

    Attributes:
        role: One of the pinned agent roles: ``planner`` | ``researcher`` |
            ``analyst`` | ``forecaster`` | ``critic``.
        title: Human-readable specialty shown in the marketplace UI, e.g.
            "Competitive Landscape Researcher".
        system_prompt: The full system prompt this specialist runs with.
    """

    role: str
    title: str
    system_prompt: str


class DagNode(TypedDict):
    """One subtask in a template's expected DAG (pinned keys, exactly these).

    Attributes:
        id: Stable subtask id (``t1`` ... ``tN``); referenced by other nodes'
            ``depends_on``.
        title: Human-readable subtask title; the planner keeps these verbatim
            so report sections line up.
        agent: Pinned agent role that executes the subtask.
        depends_on: Ids of subtasks that must finish first (may be empty for
            parallel roots).
    """

    id: str
    title: str
    agent: str
    depends_on: list[str]


class TemplateDict(TypedDict):
    """The pinned marketplace ``Template`` shape (docs/INTERFACES.md).

    Attributes:
        id: Exact pinned template id, e.g. ``market_research_team``.
        name: Display name shown in the template marketplace.
        description: One-paragraph pitch of what the team does and when to
            hire it.
        tags: Short lowercase keyword tags for gallery filtering.
        team: The specialist members (planner is engine-owned and therefore
            not listed; it is driven by ``planner_prompt``).
        planner_prompt: Instructions for the planner agent on how to
            decompose this team's kind of mission into ``expected_dag``.
        sample_mission: A vivid, realistic example mission for the UI.
        expected_dag: The subtask graph a typical mission decomposes into.
        report_outline: Section list the final report will follow, aligned
            with the team's promised outputs.
    """

    id: str
    name: str
    description: str
    tags: list[str]
    team: list[TeamMember]
    planner_prompt: str
    sample_mission: str
    expected_dag: list[DagNode]
    report_outline: list[str]
