"""Math and env-var tests for realtime.token_meter."""

from __future__ import annotations

import pytest

from realtime.token_meter import (
    DEFAULT_COST_PER_1M_INPUT,
    DEFAULT_COST_PER_1M_OUTPUT,
    TokenMeter,
    cost_of_tokens,
)

# env var names under test (canonical, from docs/INTERFACES.md)
ENV_IN = "COST_PER_1M_INPUT_TOKENS"
ENV_OUT = "COST_PER_1M_OUTPUT_TOKENS"


def test_default_rates_and_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_IN, raising=False)
    monkeypatch.delenv(ENV_OUT, raising=False)
    meter = TokenMeter()
    assert meter.cost_per_1m_input_tokens == DEFAULT_COST_PER_1M_INPUT == 0.11
    assert meter.cost_per_1m_output_tokens == DEFAULT_COST_PER_1M_OUTPUT == 0.11


def test_env_rates_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_IN, "0.50")
    monkeypatch.setenv(ENV_OUT, "1.50")
    meter = TokenMeter()
    assert meter.cost_per_1m_input_tokens == 0.50
    assert meter.cost_per_1m_output_tokens == 1.50
    tally = meter.record("analyst", input_tokens=1_000_000, output_tokens=1_000_000)
    assert tally["cost_usd"] == pytest.approx(2.00)


def test_invalid_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_IN, "not-a-number")
    monkeypatch.setenv(ENV_OUT, "-3")  # negative prices are config errors
    meter = TokenMeter()
    assert meter.cost_per_1m_input_tokens == 0.11
    assert meter.cost_per_1m_output_tokens == 0.11


def test_cost_math_explicit_rates() -> None:
    assert cost_of_tokens(2_000_000, 1_000_000, 0.11, 0.11) == pytest.approx(0.33)
    assert cost_of_tokens(0, 0, 0.11, 0.11) == 0.0
    assert cost_of_tokens(500_000, 0, 0.20, 2.00) == pytest.approx(0.10)


def test_record_accumulates_per_agent_and_totals() -> None:
    meter = TokenMeter(cost_per_1m_input_tokens=0.11, cost_per_1m_output_tokens=0.11)
    meter.record("analyst", input_tokens=1_000_000, output_tokens=0)
    meter.record("analyst", input_tokens=0, output_tokens=1_000_000)
    meter.record("critic", input_tokens=1_000_000, output_tokens=1_000_000)
    snap = meter.snapshot()
    assert snap["per_agent"]["analyst"] == {
        "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cost_usd": 0.22,
    }
    assert snap["per_agent"]["critic"]["cost_usd"] == 0.22
    assert snap["totals"] == {
        "input_tokens": 2_000_000, "output_tokens": 2_000_000, "cost_usd": 0.44,
    }
    assert meter.run_total_usd() == pytest.approx(0.44)


def test_record_clamps_bad_counts() -> None:
    meter = TokenMeter()
    meter.record("analyst", input_tokens=-100, output_tokens=0)
    meter.record("analyst", input_tokens=True, output_tokens="7")  # type: ignore[arg-type]
    snap = meter.snapshot()
    assert snap["per_agent"]["analyst"]["input_tokens"] == 0
    assert snap["per_agent"]["analyst"]["output_tokens"] == 7


def test_ingest_token_update_honours_declared_cost() -> None:
    meter = TokenMeter(cost_per_1m_input_tokens=0.11, cost_per_1m_output_tokens=0.11)
    tally = meter.ingest_token_update({
        "agent": "planner", "input_tokens": 1_000, "output_tokens": 200,
        "cost_usd": 0.00123, "run_total_usd": 0.00123,
    })
    assert tally["input_tokens"] == 1_000
    assert tally["cost_usd"] == pytest.approx(0.00123)  # declared wins over recomputed


def test_ingest_token_update_recomputes_when_cost_missing() -> None:
    meter = TokenMeter(cost_per_1m_input_tokens=0.11, cost_per_1m_output_tokens=0.11)
    tally = meter.ingest_token_update({
        "agent": "analyst", "input_tokens": 1_000_000, "output_tokens": 0,
    })
    assert tally["cost_usd"] == pytest.approx(0.11)


def test_merge_meters_and_snapshots() -> None:
    a = TokenMeter(cost_per_1m_input_tokens=0.11, cost_per_1m_output_tokens=0.11)
    a.record("analyst", input_tokens=1_000_000, output_tokens=0)
    b = TokenMeter(cost_per_1m_input_tokens=0.5, cost_per_1m_output_tokens=0.5)
    b.record("analyst", input_tokens=0, output_tokens=1_000_000)
    b.record("critic", input_tokens=2_000_000, output_tokens=0)

    a.merge(b)
    snap = a.snapshot()
    # merged counts add; cost recomputed at the receiving meter's rates
    assert snap["per_agent"]["analyst"]["input_tokens"] == 1_000_000
    assert snap["per_agent"]["analyst"]["output_tokens"] == 1_000_000
    assert snap["per_agent"]["analyst"]["cost_usd"] == pytest.approx(0.22)
    assert snap["per_agent"]["critic"]["input_tokens"] == 2_000_000
    assert snap["totals"]["input_tokens"] == 3_000_000

    # snapshot dict form
    c = TokenMeter()
    c.merge({"per_agent": {"forecaster": {"input_tokens": 10, "output_tokens": 5}}})
    assert c.snapshot()["per_agent"]["forecaster"]["input_tokens"] == 10

    with pytest.raises(TypeError):
        c.merge(42)  # type: ignore[arg-type]


def test_from_snapshot_and_from_events() -> None:
    meter = TokenMeter.from_snapshot({
        "per_agent": {"planner": {"input_tokens": 100, "output_tokens": 50}},
    })
    assert meter.snapshot()["per_agent"]["planner"]["input_tokens"] == 100

    events = [
        {"type": "run_started"},
        {"type": "token_update",
         "payload": {"agent": "analyst", "input_tokens": 300, "output_tokens": 100,
                     "cost_usd": 0.0, "run_total_usd": 0.0}},
        {"type": "token_update",
         "payload": {"agent": "analyst", "input_tokens": 200, "output_tokens": 50,
                     "cost_usd": 0.0, "run_total_usd": 0.0}},
    ]
    replayed = TokenMeter.from_events(events)
    snap = replayed.snapshot()
    assert snap["per_agent"]["analyst"]["input_tokens"] == 500
    assert snap["per_agent"]["analyst"]["output_tokens"] == 150


def test_breakdown_table_and_format() -> None:
    meter = TokenMeter(cost_per_1m_input_tokens=0.11, cost_per_1m_output_tokens=0.11)
    meter.record("critic", input_tokens=3_000_000, output_tokens=0)      # 0.33
    meter.record("analyst", input_tokens=1_000_000, output_tokens=0)     # 0.11
    rows = meter.breakdown_table()
    assert [r["agent"] for r in rows] == ["critic", "analyst"]  # cost desc
    assert rows[0]["cost_share"] == pytest.approx(0.75, abs=1e-3)
    assert rows[0]["total_tokens"] == 3_000_000

    text = meter.format_breakdown()
    assert "agent" in text and "TOTAL" in text
    assert "$0.330000" in text and "75.0%" in text

    empty = TokenMeter().format_breakdown()
    assert empty == "No token usage recorded."
