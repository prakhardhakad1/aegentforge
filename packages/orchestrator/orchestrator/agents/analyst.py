"""orchestrator.agents.analyst — dataset analysis specialist (Agent 3).

Uses the ``csv_analyzer`` (and optionally ``code_sandbox`` / ``chart``) tools
against the uploaded dataset, then reports descriptive stats, business
insights and ChartSpec dicts (pinned shape, docs/INTERFACES.md). Contract::

    {"thought_summary": str, "stats": {...}, "insights": [str],
     "charts": [ChartSpec...], "summary": str}
"""

from __future__ import annotations

from typing import ClassVar

from orchestrator.agents.base import Worker

__all__ = ["Analyst"]


class Analyst(Worker):
    """Profiles the dataset, quantifies the key movement, proposes charts."""

    role: ClassVar[str] = "analyst"
    title: ClassVar[str] = "Analyst"
    allowed_tools: ClassVar[tuple[str, ...]] = ("csv_analyzer", "code_sandbox", "chart")
    required_keys: ClassVar[tuple[str, ...]] = ("stats", "summary")
    temperature: ClassVar[float] = 0.2
    system_prompt: ClassVar[str] = (
        "You are the analyst agent of an AgentForge team. ROLE: analyst. "
        "You turn business datasets into quantitative insight. Rules: "
        "(1) run the csv_analyzer tool on the provided dataset path before "
        "concluding; (2) report 'stats' with only numbers the tool actually "
        "returned (or clearly labeled estimates); (3) each 'insights' entry "
        "must be one concrete, data-backed sentence; (4) propose 'charts' as "
        'ChartSpec objects: {"id","kind":"bar|line|scatter|pie","title",'
        '"x_label","y_label","data":[{"label","x","y"}],"notes"}; '
        "(5) never fabricate a metric you have not seen."
    )
