"""orchestrator — the AgentForge agent orchestration engine (Agent 3).

Pipeline: planner -> specialist workers (researcher / analyst / forecaster)
-> critic -> one revision pass -> structured report. Every step emits the
pinned event envelope from ``docs/INTERFACES.md`` through ``on_event``.

Public surface (import lazily to keep startup light and avoid cycles):

    from orchestrator.engine import execute_run, RunResult
    from orchestrator.llm import LLMClient
    from orchestrator.planner import Planner
    from orchestrator.tokens import TokenAccountant
    from orchestrator.memory import MemoryStore, InMemoryJSONStore

The package imports cleanly with zero third-party dependencies resolved at
import time beyond pydantic/httpx (which are core deps). ``orchestrator.report``
(Agent 6) and ``orchestrator.templates`` (Agent 8) are imported defensively at
call time — the engine degrades gracefully when they are absent.
"""

from __future__ import annotations

import importlib

__version__ = "0.1.0"

__all__ = [
    "execute_run",
    "RunResult",
    "LLMClient",
    "Planner",
    "TokenAccountant",
    "MemoryStore",
    "InMemoryJSONStore",
    "__version__",
]

_LAZY_ATTRS = {
    "execute_run": ("orchestrator.engine", "execute_run"),
    "RunResult": ("orchestrator.engine", "RunResult"),
    "LLMClient": ("orchestrator.llm", "LLMClient"),
    "Planner": ("orchestrator.planner", "Planner"),
    "TokenAccountant": ("orchestrator.tokens", "TokenAccountant"),
    "MemoryStore": ("orchestrator.memory", "MemoryStore"),
    "InMemoryJSONStore": ("orchestrator.memory", "InMemoryJSONStore"),
}


def __getattr__(name: str):
    """PEP 562 lazy attribute access so `import orchestrator` stays cheap."""
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module 'orchestrator' has no attribute {name!r}")
    module_name, attr = target
    return getattr(importlib.import_module(module_name), attr)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS))
