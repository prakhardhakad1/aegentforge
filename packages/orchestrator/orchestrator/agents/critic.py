"""orchestrator.agents.critic — quality gate and verdict specialist (Agent 3).

Reviews every artifact and upstream step output, flags unsupported claims,
emits :class:`~orchestrator.messages.RevisionRequest`s for weak subtasks and
finishes with a clear verdict. The engine performs at most ONE revision pass
based on these requests, then asks the critic to re-review. Contract::

    {"thought_summary": str, "approved": bool, "issues": [str|dict],
     "revision_requests": [{"target_subtask_id", "reason", "instruction",
                            "severity"}],
     "final_verdict": str, "summary": str}
"""

from __future__ import annotations

from typing import Any, ClassVar

from orchestrator.agents.base import Worker
from orchestrator.messages import CriticVerdict, RevisionRequest, TaskAssignment, WorkerOutput

__all__ = ["Critic"]


class Critic(Worker):
    """Reviews all outputs; the last word before the report is written."""

    role: ClassVar[str] = "critic"
    title: ClassVar[str] = "Critic"
    allowed_tools: ClassVar[tuple[str, ...]] = ()
    required_keys: ClassVar[tuple[str, ...]] = ("approved", "final_verdict", "summary")
    temperature: ClassVar[float] = 0.1
    system_prompt: ClassVar[str] = (
        "You are the critic agent of an AgentForge team. ROLE: critic. "
        "You are the quality gate before anything reaches the decision-maker. "
        "Rules: (1) check every upstream claim against its stated evidence; "
        "(2) flag vague or unsupported claims in 'issues'; (3) request a "
        "revision with 'revision_requests' ONLY when a subtask's core "
        "conclusion is unsupported — name its exact subtask id in "
        "'target_subtask_id'; (4) end with a decisive 'final_verdict'. "
        "Be strict but pragmatic: revision passes cost time."
    )

    def verdict(self, output: WorkerOutput, assignment: TaskAssignment) -> CriticVerdict:
        """Build the structured :class:`CriticVerdict` from a critic output."""
        content = output.content
        requests = [
            RevisionRequest.from_dict(item)
            for item in (content.get("revision_requests") or [])
            if isinstance(item, dict) and str(item.get("target_subtask_id") or "").strip()
        ]
        # Drop requests aimed at subtasks that do not exist or are the critic itself.
        known_ids = {up.get("subtask_id") for up in assignment.upstream}
        requests = [
            request for request in requests
            if request.target_subtask_id in known_ids
            and request.target_subtask_id != output.subtask_id
        ]
        issues = content.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        approved = bool(content.get("approved")) and not requests
        return CriticVerdict(
            subtask_id=output.subtask_id,
            approved=approved,
            issues=[str(issue) for issue in issues],
            revision_requests=requests,
            final_verdict=str(content.get("final_verdict") or ""),
            summary=str(content.get("summary") or output.summary),
            mock=output.mock,
        )
