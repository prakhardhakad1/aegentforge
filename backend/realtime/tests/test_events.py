"""Validation tests for realtime.events — the pinned envelope contract."""

from __future__ import annotations

import pytest

from realtime.events import (
    AGENT_ROLES,
    ARTIFACT_KINDS,
    EVENT_TYPES,
    EventValidationError,
    chart_spec,
    is_iso_utc_ts,
    is_valid_event,
    make_event,
    utc_now_iso,
    validate_event,
    validate_event_dict,
)


# ── pinned constants ─────────────────────────────────────────────────────


def test_pinned_event_types_match_interfaces() -> None:
    assert EVENT_TYPES == (
        "run_started",
        "plan_created",
        "agent_started",
        "thought_summary",
        "tool_call",
        "tool_result",
        "artifact_created",
        "step_completed",
        "agent_finished",
        "run_finished",
        "run_failed",
        "token_update",
    )


def test_pinned_agent_roles_and_artifact_kinds_match_interfaces() -> None:
    assert AGENT_ROLES == ("planner", "researcher", "analyst", "forecaster", "critic")
    assert ARTIFACT_KINDS == (
        "chart", "table", "text", "prediction", "recommendation",
        "report_markdown", "report_pdf", "file",
    )


# ── make_event happy paths ───────────────────────────────────────────────


def test_make_event_valid_envelope() -> None:
    event = make_event(
        "agent_started", "run-1", 3,
        agent="analyst",
        payload={"subtask_id": "st3", "title": "Analyze data"},
    )
    assert event["type"] == "agent_started"
    assert event["run_id"] == "run-1"
    assert event["seq"] == 3
    assert event["agent"] == "analyst"
    assert event["payload"]["subtask_id"] == "st3"
    assert is_iso_utc_ts(event["ts"])
    assert event["ts"].endswith("Z")


def test_make_event_all_pinned_types_with_valid_payloads() -> None:
    payloads = {
        "run_started": {"mission": "m", "mode": "demo"},
        "plan_created": {"subtasks": [
            {"id": "st1", "title": "Plan", "agent": "planner", "depends_on": []},
            {"id": "st2", "title": "Work", "agent": "analyst", "depends_on": ["st1"]},
        ]},
        "agent_started": {"subtask_id": "st1", "title": "Plan"},
        "thought_summary": {"subtask_id": "st1", "summary": "Thinking."},
        "tool_call": {"subtask_id": "st1", "tool": "csv_analyzer", "args_summary": "a", "ok": True},
        "tool_result": {"subtask_id": "st1", "tool": "csv_analyzer", "args_summary": "r", "ok": True},
        "artifact_created": {
            "subtask_id": "st1", "artifact_id": "art_1", "kind": "chart",
            "name": "Chart", "summary": "s",
        },
        "step_completed": {"subtask_id": "st1"},
        "agent_finished": {"subtask_id": "st1"},
        "run_finished": {"report_ready": True},
        "run_failed": {"error": "boom", "stage": "execution"},
        "token_update": {
            "agent": "analyst", "input_tokens": 100, "output_tokens": 20,
            "cost_usd": 0.0000132, "run_total_usd": 0.0000132,
        },
    }
    for seq, (event_type, payload) in enumerate(payloads.items(), start=1):
        agent = payload.get("agent") if event_type == "token_update" else None
        event = make_event(event_type, "run-1", seq, agent=agent, payload=payload)
        assert event["type"] == event_type


def test_utc_now_iso_format() -> None:
    ts = utc_now_iso()
    assert ts.endswith("Z") and "T" in ts
    assert is_iso_utc_ts(ts)


# ── make_event rejections ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"event_type": "not_a_type", "run_id": "r", "seq": 1},           # bad type
        {"event_type": "run_started", "run_id": "", "seq": 1},           # empty run_id
        {"event_type": "run_started", "run_id": "r", "seq": 0},          # seq < 1
        {"event_type": "run_started", "run_id": "r", "seq": True},       # bool seq
        {"event_type": "run_started", "run_id": "r", "seq": 1,
         "agent": "ceo"},                                                # bad agent
        {"event_type": "run_started", "run_id": "r", "seq": 1,
         "ts": "not-a-date"},                                            # bad ts
        {"event_type": "token_update", "run_id": "r", "seq": 1,
         "payload": {"agent": "intern", "input_tokens": 1,
                     "output_tokens": 1, "cost_usd": 0.0,
                     "run_total_usd": 0.0}},                             # bad token agent
    ],
)
def test_make_event_rejects_invalid_envelopes(kwargs: dict) -> None:
    with pytest.raises(EventValidationError):
        make_event(**kwargs)


@pytest.mark.parametrize(
    "payload",
    [
        {},                                                              # missing subtasks
        {"subtasks": []},                                                # empty plan
        {"subtasks": [{"id": "st1", "title": "t", "agent": "ceo"}]},     # bad role
        {"subtasks": [{"id": "st1", "title": "t", "agent": "analyst",
                       "depends_on": ["stX"]}]},                         # unknown dep
    ],
)
def test_plan_created_payload_rejections(payload: dict) -> None:
    with pytest.raises(EventValidationError):
        make_event("plan_created", "r", 1, agent="planner", payload=payload)


@pytest.mark.parametrize("kind", ["infographic", "CHART", ""])
def test_artifact_kind_must_be_pinned(kind: str) -> None:
    with pytest.raises(EventValidationError):
        make_event(
            "artifact_created", "r", 1, agent="analyst",
            payload={
                "subtask_id": "st1", "artifact_id": "a1",
                "kind": kind, "name": "n", "summary": "s",
            },
        )


def test_negative_token_counts_rejected() -> None:
    with pytest.raises(EventValidationError):
        make_event(
            "token_update", "r", 1, agent="planner",
            payload={"agent": "planner", "input_tokens": -5, "output_tokens": 0,
                     "cost_usd": 0.0, "run_total_usd": 0.0},
        )


def test_run_failed_requires_error_and_stage() -> None:
    with pytest.raises(EventValidationError):
        make_event("run_failed", "r", 1, payload={"error": "boom"})
    with pytest.raises(EventValidationError):
        make_event("run_failed", "r", 1, payload={"stage": "execution"})


def test_extra_payload_keys_are_tolerated() -> None:
    event = make_event(
        "token_update", "r", 1, agent="critic",
        payload={"agent": "critic", "input_tokens": 10, "output_tokens": 5,
                 "cost_usd": 0.0, "run_total_usd": 0.0, "simulated": True},
    )
    assert event["payload"]["simulated"] is True


# ── validate helpers ─────────────────────────────────────────────────────


def test_validate_event_roundtrip() -> None:
    event = make_event("run_finished", "r", 1, payload={"report_ready": True})
    model = validate_event(event)
    assert model.type == "run_finished"
    assert validate_event_dict(event)["seq"] == 1


def test_validate_event_rejects_non_mapping() -> None:
    with pytest.raises(EventValidationError):
        validate_event("not an event")
    assert is_valid_event(42) is False
    assert is_valid_event({"type": "run_started", "run_id": "r", "seq": 1,
                           "ts": utc_now_iso(), "agent": None}) is True


# ── chart_spec ───────────────────────────────────────────────────────────


def test_chart_spec_valid() -> None:
    spec = chart_spec(
        "chart_1", "bar", "Title", "x", "y",
        [{"label": "a", "x": 1, "y": 2}, {"y": 5}], notes="measured",
    )
    assert spec["kind"] == "bar"
    assert spec["data"][0] == {"label": "a", "x": 1, "y": 2}
    assert spec["data"][1]["label"] == "point_1"  # label defaulted
    assert spec["notes"] == "measured"


def test_chart_spec_rejections() -> None:
    with pytest.raises(EventValidationError):
        chart_spec("c", "hologram", "t", "x", "y", [{"y": 1}])
    with pytest.raises(EventValidationError):
        chart_spec("c", "bar", "t", "x", "y", [])
    with pytest.raises(EventValidationError):
        chart_spec("c", "bar", "t", "x", "y", [{"label": "a"}])  # missing y
