"""orchestrator.messages — structured inter-agent message contracts (Agent 3).

The planner, workers, critic and engine exchange these dataclasses; each has a
``to_dict()`` for the JSON-safe event payloads and RunResult steps.

Message flow::

    Planner ──TaskAssignment──▶ Worker ──WorkerOutput──▶ Engine
    Engine  ──WorkerOutputs───▶ Critic ──CriticVerdict──▶ Engine
    Critic  ──RevisionRequest──▶ Engine ──(re-run worker)──▶ Critic again
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "TaskAssignment",
    "WorkerOutput",
    "RevisionRequest",
    "CriticVerdict",
    "SubtaskStatus",
    "valid_statuses",
]


# Subtask lifecycle statuses (used in plan payloads and step records).
SubtaskStatus = str  # "pending" | "running" | "completed" | "failed" | "skipped"
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
SKIPPED = "skipped"


def valid_statuses() -> tuple[str, ...]:
    """All legal subtask statuses."""
    return (PENDING, RUNNING, COMPLETED, FAILED, SKIPPED)


@dataclass
class TaskAssignment:
    """Everything a worker needs to execute one subtask."""

    subtask_id: str
    title: str
    role: str
    guidance: str = ""
    mission: str = ""
    template_id: str | None = None
    dataset_path: str | None = None
    dataset_columns: list[str] = field(default_factory=list)
    # Digests of upstream WorkerOutputs: [{subtask_id, role, title, status,
    # summary, content}] — content included so the critic and downstream
    # workers can cite upstream numbers.
    upstream: list[dict[str, Any]] = field(default_factory=list)
    # When true this is a revision pass for a subtask the critic flagged.
    is_revision: bool = False
    revision_instruction: str = ""

    def to_prompt_context(self) -> str:
        """Render the assignment as the structured user-message block the
        workers (and the mock responder) parse."""
        lines = [
            f"MISSION: {self.mission}",
            f"SUBTASK: [{self.subtask_id}] {self.title}",
            f"ROLE: {self.role}",
        ]
        if self.guidance:
            lines.append(f"GUIDANCE: {self.guidance}")
        if self.template_id:
            lines.append(f"TEMPLATE: {self.template_id}")
        if self.dataset_path:
            lines.append(f"DATASET PATH: {self.dataset_path}")
        if self.dataset_columns:
            lines.append(f"DATASET COLUMNS: {', '.join(self.dataset_columns)}")
        if self.upstream:
            lines.append("UPSTREAM RESULTS:")
            for item in self.upstream:
                lines.append(
                    f"- SUBTASK {item.get('subtask_id')} ({item.get('role')}, "
                    f"status={item.get('status')}): {item.get('summary', '')}"
                )
                content = item.get("content")
                if isinstance(content, dict) and content:
                    compact = {
                        k: v
                        for k, v in content.items()
                        if k in ("stats", "insights", "findings", "predictions", "issues")
                    }
                    if compact:
                        lines.append(f"  DATA: {compact}")
        if self.is_revision:
            lines.append(f"REVISION REQUEST: {self.revision_instruction}")
            lines.append(
                "Address the revision request with concrete evidence; "
                "do not repeat unsupported claims."
            )
        return "\n".join(lines)


@dataclass
class WorkerOutput:
    """Structured result of one worker execution attempt."""

    subtask_id: str
    role: str
    ok: bool
    summary: str = ""
    # Role-specific structured payload (findings, stats, predictions, ...).
    content: dict[str, Any] = field(default_factory=dict)
    # Artifact dicts ready for the pinned artifact_created payload:
    # {artifact_id, kind, name, summary, path?, data?}
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    # Tool-call records: [{tool, args_summary, ok, error?}]
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    attempts: int = 1
    mock: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict."""
        return {
            "subtask_id": self.subtask_id,
            "role": self.role,
            "ok": self.ok,
            "summary": self.summary,
            "content": self.content,
            "artifacts": self.artifacts,
            "tool_events": self.tool_events,
            "error": self.error,
            "attempts": self.attempts,
            "mock": self.mock,
        }


@dataclass
class RevisionRequest:
    """The critic asks for one flagged subtask to be redone."""

    target_subtask_id: str
    reason: str
    instruction: str
    severity: str = "major"  # "minor" | "major"

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict."""
        return {
            "target_subtask_id": self.target_subtask_id,
            "reason": self.reason,
            "instruction": self.instruction,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RevisionRequest":
        """Build from a (possibly sloppy) LLM JSON dict, with coercion."""
        target = str(
            data.get("target_subtask_id")
            or data.get("subtask_id")
            or data.get("target")
            or ""
        ).strip()
        severity = str(data.get("severity") or "major").lower()
        if severity not in ("minor", "major"):
            severity = "major"
        return cls(
            target_subtask_id=target,
            reason=str(data.get("reason") or "Claim not adequately supported."),
            instruction=str(data.get("instruction") or data.get("fix") or "Re-run with concrete evidence."),
            severity=severity,
        )


@dataclass
class CriticVerdict:
    """Structured verdict parsed from the critic worker's output."""

    subtask_id: str
    approved: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    revision_requests: list[RevisionRequest] = field(default_factory=list)
    final_verdict: str = ""
    summary: str = ""
    mock: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict."""
        return {
            "subtask_id": self.subtask_id,
            "approved": self.approved,
            "issues": self.issues,
            "revision_requests": [r.to_dict() for r in self.revision_requests],
            "final_verdict": self.final_verdict,
            "summary": self.summary,
            "mock": self.mock,
        }
