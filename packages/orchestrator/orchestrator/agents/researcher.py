"""orchestrator.agents.researcher — web research specialist (Agent 3).

Uses the ``web_search`` tool to gather public context (benchmarks, competitor
facts, comparable cases), then synthesizes findings where every claim carries
a source URL. The structured contract is::

    {"thought_summary": str, "findings": [str], "source_urls": [str],
     "summary": str}
"""

from __future__ import annotations

from typing import ClassVar

from orchestrator.agents.base import Worker

__all__ = ["Researcher"]


class Researcher(Worker):
    """Researches the public web and synthesizes sourced findings."""

    role: ClassVar[str] = "researcher"
    title: ClassVar[str] = "Researcher"
    allowed_tools: ClassVar[tuple[str, ...]] = ("web_search",)
    required_keys: ClassVar[tuple[str, ...]] = ("findings", "summary")
    temperature: ClassVar[float] = 0.3
    system_prompt: ClassVar[str] = (
        "You are the researcher agent of an AgentForge team. ROLE: researcher. "
        "You gather public context for a business mission: market facts, "
        "benchmarks, competitor moves and comparable cases. Rules: "
        "(1) search before you claim; (2) every finding must be a single "
        "concrete sentence; (3) list the source URLs you actually used in "
        "'source_urls'; (4) never invent sources, numbers or quotes; "
        "(5) finish with a crisp 1-2 sentence 'summary'."
    )
