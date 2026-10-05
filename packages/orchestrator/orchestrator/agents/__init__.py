"""orchestrator.agents — specialist workers driven by the shared LLM client.

Each worker knows its role, system prompt, allowed tools and structured
output contract; the base class owns input-context assembly, the tool
function-calling loop, JSON parsing/validation, artifact extraction and
token accounting. Specializations only declare their contract:

* :class:`Researcher` — web_search, findings + source URLs
* :class:`Analyst`    — csv_analyzer / code_sandbox / chart, stats + ChartSpecs
* :class:`Forecaster` — predictions with confidence + basis
* :class:`Critic`     — reviews everything, emits revision requests + verdict
"""

from __future__ import annotations

from .base import Worker, WorkerError, WorkerHooks
from .analyst import Analyst
from .critic import Critic
from .forecaster import Forecaster
from .researcher import Researcher

__all__ = [
    "Worker",
    "WorkerError",
    "WorkerHooks",
    "Researcher",
    "Analyst",
    "Forecaster",
    "Critic",
    "build_worker",
    "build_default_workers",
]


def build_worker(role: str, llm: object, registry: object, hooks: WorkerHooks) -> Worker:
    """Instantiate the specialization for *role*.

    Args:
        role: one of the pinned worker roles.
        llm: :class:`orchestrator.llm.LLMClient`.
        registry: optional AgentForge tool registry (duck-typed; any object
            exposing ``function_calling_specs()`` and ``run(name, inputs)``).
        hooks: engine-provided event/token callbacks.

    Raises:
        WorkerError: unknown role.
    """
    classes = {
        "researcher": Researcher,
        "analyst": Analyst,
        "forecaster": Forecaster,
        "critic": Critic,
    }
    cls = classes.get(role)
    if cls is None:
        raise WorkerError(f"no worker class for role {role!r}")
    return cls(llm=llm, registry=registry, hooks=hooks)  # type: ignore[call-arg]


def build_default_workers(
    llm: object, registry: object, hooks: WorkerHooks
) -> dict[str, Worker]:
    """One worker instance per pinned worker role, keyed by role."""
    return {role: build_worker(role, llm, registry, hooks) for role in
            ("researcher", "analyst", "forecaster", "critic")}
