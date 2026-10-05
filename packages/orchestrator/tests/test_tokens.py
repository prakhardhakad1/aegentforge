"""Tests for orchestrator.tokens: counters, cost math, env parsing, snapshots."""

from __future__ import annotations

import pytest

from orchestrator.tokens import TokenAccountant


class TestAccountant:
    def test_add_accumulates_per_agent(self):
        accountant = TokenAccountant(cost_per_1m_input=0.0, cost_per_1m_output=0.0)
        accountant.add("analyst", 100, 50)
        accountant.add("analyst", 30, 20)
        usage = accountant.per_agent["analyst"]
        assert usage.input_tokens == 130 and usage.output_tokens == 70
        assert usage.calls == 2

    def test_snapshot_shape_and_math(self):
        accountant = TokenAccountant(cost_per_1m_input=1.0, cost_per_1m_output=2.0)
        accountant.add("critic", 1_000_000, 500_000)
        snapshot = accountant.snapshot("critic")
        assert set(snapshot) == {"agent", "input_tokens", "output_tokens", "cost_usd", "run_total_usd"}
        assert snapshot["input_tokens"] == 1_000_000
        assert snapshot["cost_usd"] == pytest.approx(1.0 + 2.0 * 0.5)
        assert snapshot["run_total_usd"] == pytest.approx(2.0)

    def test_totals_across_agents(self):
        accountant = TokenAccountant(cost_per_1m_input=0.0, cost_per_1m_output=0.0)
        accountant.add("analyst", 100, 10)
        accountant.add("critic", 40, 5)
        totals = accountant.to_dict()["totals"]
        assert totals["input_tokens"] == 140 and totals["output_tokens"] == 15

    def test_to_dict_pinned_shape(self):
        accountant = TokenAccountant()
        accountant.add("planner", 10, 2)
        data = accountant.to_dict()
        assert set(data) == {"per_agent", "totals"}
        assert set(data["per_agent"]["planner"]) == {"input_tokens", "output_tokens", "cost_usd"}

    def test_negative_tokens_clamped(self):
        accountant = TokenAccountant()
        accountant.add("analyst", -5, 10)
        assert accountant.per_agent["analyst"].input_tokens == 0

    def test_unknown_agent_snapshot_zeroed(self):
        accountant = TokenAccountant()
        snapshot = accountant.snapshot("ghost")
        assert snapshot["input_tokens"] == 0 and snapshot["cost_usd"] == 0.0


class TestFromEnv:
    def test_env_costs_used(self, monkeypatch):
        monkeypatch.setenv("COST_PER_1M_INPUT_TOKENS", "0.5")
        monkeypatch.setenv("COST_PER_1M_OUTPUT_TOKENS", "1.5")
        accountant = TokenAccountant.from_env()
        accountant.add("analyst", 1_000_000, 1_000_000)
        assert accountant.total_cost() == pytest.approx(2.0)

    def test_garbage_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("COST_PER_1M_INPUT_TOKENS", "not-a-number")
        accountant = TokenAccountant.from_env()
        assert accountant.cost_per_1m_input == 0.11

    def test_missing_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("COST_PER_1M_OUTPUT_TOKENS", raising=False)
        accountant = TokenAccountant.from_env()
        assert accountant.cost_per_1m_output == 0.11
