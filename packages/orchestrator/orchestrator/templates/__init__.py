"""orchestrator.templates — the marketplace template teams (Agent 8).

Three ready-to-run agent teams for the AgentForge template marketplace:

- ``market_research_team`` — researcher x2 + analyst + critic: competitor
  landscape, positioning gaps, go-to-market recommendations.
- ``sales_insights_team`` — analyst + forecaster + critic: pipeline/revenue
  trends, at-risk segments, forecast.
- ``support_triage_team`` — researcher + analyst + critic: complaint themes,
  resolution-time analysis, staffing recommendations.

Import contract (load-bearing for the orchestrator engine, which imports this
package defensively): importing this package has NO side effects and pulls in
ONLY the standard library at runtime. Consumers:

- ``get_template(template_id)`` — lookup; raises a helpful ``KeyError``.
- ``TEMPLATES`` / ``TEMPLATE_IDS`` / ``TEMPLATES_BY_ID`` — the registry.
- ``validate_all()`` / ``validate_template`` — pinned-shape validation.
- ``as_api_shape(template)`` — deep copy with exactly the pinned Template
  keys, for the backend's ``GET /api/templates``.
- ``is_dag_acyclic`` / ``dag_problems`` — DAG utilities.
- ``MARKET_RESEARCH_TEAM`` / ``SALES_INSIGHTS_TEAM`` / ``SUPPORT_TRIAGE_TEAM``
  — the individual template dicts (pinned shape, plain JSON-safe dicts).
"""

from __future__ import annotations

from orchestrator.templates._types import DagNode, TeamMember, TemplateDict
from orchestrator.templates.market_research import MARKET_RESEARCH_TEAM
from orchestrator.templates.registry import (
    DAG_NODE_KEYS,
    PINNED_ROLES,
    TEAM_MEMBER_KEYS,
    TEMPLATE_IDS,
    TEMPLATE_KEYS,
    TEMPLATES,
    TEMPLATES_BY_ID,
    as_api_shape,
    dag_problems,
    get_template,
    is_dag_acyclic,
    validate_all,
    validate_template,
)
from orchestrator.templates.sales_insights import SALES_INSIGHTS_TEAM
from orchestrator.templates.support_triage import SUPPORT_TRIAGE_TEAM

__all__ = [
    "DAG_NODE_KEYS",
    "MARKET_RESEARCH_TEAM",
    "PINNED_ROLES",
    "SALES_INSIGHTS_TEAM",
    "SUPPORT_TRIAGE_TEAM",
    "TEAM_MEMBER_KEYS",
    "TEMPLATE_IDS",
    "TEMPLATE_KEYS",
    "TEMPLATES",
    "TEMPLATES_BY_ID",
    "DagNode",
    "TeamMember",
    "TemplateDict",
    "as_api_shape",
    "dag_problems",
    "get_template",
    "is_dag_acyclic",
    "validate_all",
    "validate_template",
]
