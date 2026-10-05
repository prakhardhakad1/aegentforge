"""Tests for orchestrator.planner: heuristic plans, validation, LLM path."""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.examples.missions import EXAMPLES
from orchestrator.planner import (
    Plan,
    PlanValidationError,
    Planner,
    Subtask,
    heuristic_plan,
)
from orchestrator.llm import LLMClient


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Heuristic planner vs the example expected plans
# ---------------------------------------------------------------------------


class TestHeuristicPlans:
    @pytest.mark.parametrize("key", ["churn", "ev", "support"])
    def test_examples_match_expected_plan(self, key):
        example = EXAMPLES[key]
        plan = heuristic_plan(example.mission, example.dataset_columns or None)
        actual = [
            {"id": s.id, "title": s.title, "agent": s.agent, "depends_on": s.depends_on}
            for s in plan.subtasks
        ]
        assert actual == example.expected_plan

    @pytest.mark.parametrize("key", ["churn", "ev", "support"])
    def test_plans_are_valid_dags(self, key):
        example = EXAMPLES[key]
        plan = heuristic_plan(example.mission, example.dataset_columns or None)
        plan.validate()  # must not raise
        order = [s.id for s in plan.topological_order()]
        for sub in plan.subtasks:
            for dep in sub.depends_on:
                assert order.index(dep) < order.index(sub.id)

    def test_single_critic_near_end(self):
        plan = heuristic_plan(EXAMPLES["churn"].mission)
        critics = [s for s in plan.subtasks if s.agent == "critic"]
        assert len(critics) == 1
        order = [s.id for s in plan.topological_order()]
        # The critic must be the last action subtask in topo order.
        action_ids = [s.id for s in plan.subtasks if not s.is_revision_slot]
        action_order = [sid for sid in order if sid in action_ids]
        assert action_order[-1] == critics[0].id

    def test_revision_slot_present_and_hangs_off_critic(self):
        plan = heuristic_plan("Research the market")
        slots = plan.revision_slots
        assert len(slots) == 1
        critic = plan.critic
        assert critic.id in slots[0].depends_on

    def test_dataset_forces_analyst(self):
        plan = heuristic_plan("Look into this please", ["col_a", "col_b"])
        assert "analyst" in [s.agent for s in plan.subtasks]

    def test_no_signal_defaults_to_researcher_plus_critic(self):
        plan = heuristic_plan("Do the thing")
        agents = [s.agent for s in plan.subtasks if not s.is_revision_slot]
        assert agents == ["researcher", "critic"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _plan(*subtasks: Subtask) -> Plan:
    return Plan(subtasks=list(subtasks))


class TestValidation:
    def test_cycle_detected(self):
        plan = _plan(
            Subtask("t1", "a", "analyst", ["t2"]),
            Subtask("t2", "b", "forecaster", ["t1"]),
            Subtask("t3", "c", "critic", ["t1", "t2"]),
        )
        with pytest.raises(PlanValidationError):
            plan.validate()

    def test_duplicate_ids_rejected(self):
        plan = _plan(
            Subtask("t1", "a", "analyst"),
            Subtask("t1", "b", "critic", ["t1"]),
        )
        with pytest.raises(PlanValidationError):
            plan.validate()

    def test_unknown_dependency_rejected(self):
        plan = _plan(
            Subtask("t1", "a", "analyst", ["ghost"]),
            Subtask("t2", "b", "critic", ["t1"]),
        )
        with pytest.raises(PlanValidationError):
            plan.validate()

    def test_two_critics_rejected(self):
        plan = _plan(
            Subtask("t1", "a", "analyst"),
            Subtask("t2", "c1", "critic", ["t1"]),
            Subtask("t3", "c2", "critic", ["t1"]),
        )
        with pytest.raises(PlanValidationError):
            plan.validate()

    def test_non_worker_role_rejected(self):
        plan = _plan(
            Subtask("t1", "a", "planner"),
            Subtask("t2", "b", "critic", ["t1"]),
        )
        with pytest.raises(PlanValidationError):
            plan.validate()

    def test_subtask_after_critic_rejected(self):
        plan = _plan(
            Subtask("t1", "a", "analyst"),
            Subtask("t2", "b", "critic", ["t1"]),
            Subtask("t3", "c", "forecaster", ["t2"]),
        )
        with pytest.raises(PlanValidationError):
            plan.validate()

    def test_empty_plan_rejected(self):
        with pytest.raises(PlanValidationError):
            Plan().validate()


class TestNormalize:
    def test_critic_gains_missing_deps(self):
        plan = _plan(
            Subtask("t1", "a", "analyst"),
            Subtask("t2", "b", "forecaster"),
            Subtask("t3", "c", "critic", ["t1"]),  # misses t2
        )
        plan.normalize()
        assert set(plan.critic.depends_on) == {"t1", "t2"}
        plan.validate()

    def test_deps_deduped_and_self_deps_dropped(self):
        plan = _plan(
            Subtask("t1", "a", "analyst"),
            Subtask("t2", "b", "critic", ["t1", "t1", "t2", "ghost"]),
        )
        plan.normalize()
        assert plan.subtask("t2").depends_on == ["t1"]


# ---------------------------------------------------------------------------
# LLM-driven path (stub client) + facade
# ---------------------------------------------------------------------------


class _StubLLM:
    """Minimal LLMClient stand-in for planner tests."""

    def __init__(self, mock: bool, payload=None, error: Exception | None = None):
        self._mock = mock
        self._payload = payload
        self._error = error
        self.last_response = None
        self.calls = 0

    @property
    def is_mock(self) -> bool:
        return self._mock

    async def complete_json(self, messages, required_keys=None, schema_hint=None, **kwargs):
        self.calls += 1
        if self._error:
            raise self._error
        return self._payload


class TestPlannerFacade:
    def test_llm_plan_accepted_when_valid(self):
        payload = {
            "subtasks": [
                {"id": "a", "title": "Research", "agent": "researcher", "depends_on": [], "guidance": "g"},
                {"id": "b", "title": "Review", "agent": "critic", "depends_on": ["a"], "guidance": "g"},
            ]
        }
        planner = Planner(_StubLLM(mock=True, payload=payload))
        # call the LLM path directly (facade skips it in mock mode)
        plan = run(planner._llm_plan("Mission", None, None))
        assert plan is not None and plan.strategy == "llm"
        assert plan.critic.depends_on == ["a"]

    def test_llm_plan_rejected_when_cyclic(self):
        payload = {
            "subtasks": [
                {"id": "a", "title": "A", "agent": "analyst", "depends_on": ["b"]},
                {"id": "b", "title": "B", "agent": "forecaster", "depends_on": ["a"]},
                {"id": "c", "title": "C", "agent": "critic", "depends_on": ["a", "b"]},
            ]
        }
        planner = Planner(_StubLLM(mock=True, payload=payload))
        assert run(planner._llm_plan("Mission", None, None)) is None

    def test_facade_falls_back_to_heuristic_in_mock_mode(self):
        stub = _StubLLM(mock=True)
        planner = Planner(stub)
        plan = run(planner.plan("Analyze the churn data"))
        assert plan.strategy == "heuristic"
        assert stub.calls == 0  # never asked the LLM in mock mode

    def test_facade_uses_llm_in_live_mode(self):
        payload = {
            "subtasks": [
                {"id": "a", "title": "Research", "agent": "researcher", "depends_on": []},
                {"id": "b", "title": "Review", "agent": "critic", "depends_on": ["a"]},
            ]
        }
        stub = _StubLLM(mock=False, payload=payload)
        planner = Planner(stub)
        plan = run(planner.plan("Research the market"))
        assert plan.strategy == "llm" and stub.calls == 1

    def test_facade_falls_back_when_llm_errors(self):
        stub = _StubLLM(mock=False, error=RuntimeError("provider down"))
        planner = Planner(stub)
        plan = run(planner.plan("Analyze the data"))
        assert plan.strategy == "heuristic"

    def test_empty_mission_rejected(self):
        planner = Planner(LLMClient())
        with pytest.raises(PlanValidationError):
            run(planner.plan("   "))

    def test_usage_callback_invoked(self):
        payload = {
            "subtasks": [
                {"id": "a", "title": "Research", "agent": "researcher", "depends_on": []},
                {"id": "b", "title": "Review", "agent": "critic", "depends_on": ["a"]},
            ]
        }
        stub = _StubLLM(mock=True, payload=payload)
        stub.last_response = type(
            "R", (), {"usage": type("U", (), {"input_tokens": 3, "output_tokens": 4})()}
        )()

        seen = []
        planner = Planner(stub, on_usage=lambda i, o: seen.append((i, o)))
        run(planner._llm_plan("Mission", None, None))
        assert seen == [(3, 4)]
