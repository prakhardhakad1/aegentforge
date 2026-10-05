"""orchestrator.agents.forecaster — prediction specialist (Agent 3).

Turns analyst/researcher outputs into forward-looking statements. Every
prediction carries an explicit ``confidence`` in [0, 1] and a ``basis``
sentence — vague hunches are rejected by the critic. Contract::

    {"thought_summary": str,
     "predictions": [{"claim": str, "confidence": float, "basis": str}],
     "summary": str}
"""

from __future__ import annotations

from typing import Any, ClassVar

from orchestrator.agents.base import Worker, WorkerError
from orchestrator.messages import TaskAssignment, WorkerOutput

__all__ = ["Forecaster"]


class Forecaster(Worker):
    """Projects the headline metric with explicit confidence and basis."""

    role: ClassVar[str] = "forecaster"
    title: ClassVar[str] = "Forecaster"
    allowed_tools: ClassVar[tuple[str, ...]] = ()
    required_keys: ClassVar[tuple[str, ...]] = ("predictions", "summary")
    temperature: ClassVar[float] = 0.2
    system_prompt: ClassVar[str] = (
        "You are the forecaster agent of an AgentForge team. ROLE: forecaster. "
        "You produce simple, defensible predictions from the analyst's stats "
        "or the researcher's findings. Rules: (1) every prediction needs "
        "'claim', 'confidence' (0-1 float) and 'basis' naming the evidence "
        "used; (2) no prediction without stated basis; (3) prefer ranges and "
        "directional claims over false precision; (4) 1-4 predictions, ranked "
        "by confidence."
    )

    def _validate_predictions(self, content: dict[str, Any], subtask_id: str) -> None:
        """Confidence must be a float in [0, 1]; claims must be non-empty."""
        predictions = content.get("predictions")
        if not isinstance(predictions, list) or not predictions:
            raise WorkerError(f"forecaster produced no predictions for {subtask_id}")
        for index, prediction in enumerate(predictions):
            if not isinstance(prediction, dict):
                raise WorkerError(f"prediction #{index} is not an object")
            try:
                confidence = float(prediction.get("confidence", 0.0))
            except (TypeError, ValueError) as exc:
                raise WorkerError(
                    f"prediction #{index} confidence is not a number"
                ) from exc
            prediction["confidence"] = max(0.0, min(1.0, confidence))
            if not str(prediction.get("claim") or "").strip():
                raise WorkerError(f"prediction #{index} has an empty claim")

    async def run(self, assignment: TaskAssignment) -> WorkerOutput:
        """Run the base loop, then clamp/validate the prediction payloads."""
        output = await super().run(assignment)
        if output.ok:
            self._validate_predictions(output.content, assignment.subtask_id)
        return output
