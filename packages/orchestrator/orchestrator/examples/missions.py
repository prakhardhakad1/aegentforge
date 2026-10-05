"""Mission fixtures for the three AgentForge worked examples (Agent 3).

Each :class:`ExampleMission` bundles the mission text, the template id it
would use in production, the optional bundled dataset (path + columns), and
the ``expected_plan`` — the exact subtask structure the heuristic planner
emits offline (LLM_MODE=mock, no template package installed). These doubles
power the demo runner and the planner/engine tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["ExampleMission", "EXAMPLES", "get_example", "list_examples"]

_DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class ExampleMission:
    """One fully specified demo mission."""

    key: str
    title: str
    mission: str
    template_id: str | None
    dataset_path: str | None
    dataset_columns: list[str]
    expected_plan: list[dict[str, Any]] = field(default_factory=list)

    def expected_plan_json(self) -> str:
        """Pretty-printed expected plan (docs/plan JSON for humans + tests)."""
        return json.dumps(self.expected_plan, indent=2)


def _example(key: str) -> str:
    """Absolute path to a bundled example CSV."""
    return str(_DATA_DIR / key)


CHURN_CSV = _example("churn_sample.csv")
TICKETS_CSV = _example("support_tickets_sample.csv")

CHURN_COLUMNS = [
    "month", "plan_tier", "region", "active_users", "churned_users",
    "support_tickets", "nps",
]
TICKET_COLUMNS = [
    "week", "category", "ticket_count", "avg_resolution_hours", "csat",
]

EXAMPLES: dict[str, ExampleMission] = {
    "churn": ExampleMission(
        key="churn",
        title="Churn spike analysis (with CSV)",
        mission=(
            "Our customer churn spiked in Q3 — analyze the data and recommend "
            "three fixes, then forecast the churn trajectory for next quarter."
        ),
        template_id="sales_insights_team",
        dataset_path=CHURN_CSV,
        dataset_columns=CHURN_COLUMNS,
        expected_plan=[
            {
                "id": "t1",
                "title": "Analyze the data behind: Our customer churn spiked",
                "agent": "analyst",
                "depends_on": [],
            },
            {
                "id": "t2",
                "title": "Forecast the trajectory for: Our customer churn spiked",
                "agent": "forecaster",
                "depends_on": ["t1"],
            },
            {
                "id": "t3",
                "title": "Critical review of outputs for: Our customer churn spiked",
                "agent": "critic",
                "depends_on": ["t1", "t2"],
            },
            {
                "id": "t3_rev",
                "title": "Revision pass for flagged subtasks (runs only if the critic flags issues)",
                "agent": "forecaster",
                "depends_on": ["t3"],
            },
        ],
    ),
    "ev": ExampleMission(
        key="ev",
        title="EV fast-charging market research",
        mission=(
            "Research the EV fast-charging market and forecast charger "
            "adoption growth through 2027 to help us decide whether to enter."
        ),
        template_id="market_research_team",
        dataset_path=None,
        dataset_columns=[],
        expected_plan=[
            {
                "id": "t1",
                "title": "Research context for: Research the EV fast-charging",
                "agent": "researcher",
                "depends_on": [],
            },
            {
                "id": "t2",
                "title": "Forecast the trajectory for: Research the EV fast-charging",
                "agent": "forecaster",
                "depends_on": ["t1"],
            },
            {
                "id": "t3",
                "title": "Critical review of outputs for: Research the EV fast-charging",
                "agent": "critic",
                "depends_on": ["t1", "t2"],
            },
            {
                "id": "t3_rev",
                "title": "Revision pass for flagged subtasks (runs only if the critic flags issues)",
                "agent": "forecaster",
                "depends_on": ["t3"],
            },
        ],
    ),
    "support": ExampleMission(
        key="support",
        title="Support ticket triage (with CSV)",
        mission=(
            "Support ticket volumes are spiking — analyze the ticket data, "
            "research how comparable SaaS teams fixed it, and recommend fixes "
            "for the top pain points."
        ),
        template_id="support_triage_team",
        dataset_path=TICKETS_CSV,
        dataset_columns=TICKET_COLUMNS,
        expected_plan=[
            {
                "id": "t1",
                "title": "Research context for: Support ticket volumes are",
                "agent": "researcher",
                "depends_on": [],
            },
            {
                "id": "t2",
                "title": "Analyze the data behind: Support ticket volumes are",
                "agent": "analyst",
                "depends_on": ["t1"],
            },
            {
                "id": "t3",
                "title": "Critical review of outputs for: Support ticket volumes are",
                "agent": "critic",
                "depends_on": ["t1", "t2"],
            },
            {
                "id": "t3_rev",
                "title": "Revision pass for flagged subtasks (runs only if the critic flags issues)",
                "agent": "analyst",
                "depends_on": ["t3"],
            },
        ],
    ),
}


def get_example(key: str) -> ExampleMission:
    """Fetch one example by key; raises KeyError with the valid keys."""
    if key not in EXAMPLES:
        raise KeyError(f"unknown example {key!r}; valid keys: {sorted(EXAMPLES)}")
    return EXAMPLES[key]


def list_examples() -> list[str]:
    """Sorted example keys (used by the demo CLI)."""
    return sorted(EXAMPLES)
