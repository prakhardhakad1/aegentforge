"""Shared pytest fixtures for the orchestrator test suite (Agent 3).

Guarantees hermeticity: LLM_MODE=mock (no network, ever) and the engine's
tool registry seam is stubbed out so no real web_search/http call can happen
from a worker during tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Fallback import path when the package is not pip-installed (e.g. CI cold start).
_REPO_ORCH = Path(__file__).resolve().parents[1]  # packages/orchestrator
try:
    import orchestrator  # noqa: F401
except ImportError:
    sys.path.insert(0, str(_REORCH))


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Force offline mock mode + deterministic costs for every test."""
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("COST_PER_1M_INPUT_TOKENS", "0.11")
    monkeypatch.setenv("COST_PER_1M_OUTPUT_TOKENS", "0.22")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_real_tools(monkeypatch):
    """Stub the engine's tool-registry seam so tests never touch the network.

    (The demo runs may use the real registry; tests must not.)
    """
    import orchestrator.engine as engine_mod

    monkeypatch.setattr(engine_mod, "_default_tool_registry", lambda run_id: None)
    yield


class EventCollector:
    """Callable event sink collecting pinned envelopes (mimics the backend)."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, envelope: dict) -> None:
        self.events.append(envelope)

    @property
    def types(self) -> list[str]:
        """Event type sequence in emission order."""
        return [event["type"] for event in self.events]

    def by_type(self, event_type: str) -> list[dict]:
        """All envelopes of one type, in order."""
        return [event for event in self.events if event["type"] == event_type]


@pytest.fixture()
def collector() -> EventCollector:
    """A fresh EventCollector per test."""
    return EventCollector()
