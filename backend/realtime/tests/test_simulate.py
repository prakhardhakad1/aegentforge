"""End-to-end tests for realtime.simulate — the offline demo simulator."""

from __future__ import annotations

import json

import pytest

from realtime.events import (
    AGENT_ROLES,
    ARTIFACT_KINDS,
    EVENT_TYPES,
    validate_event,
)
from realtime.simulate import (
    BASE_DELAYS,
    TEMPLATE_IDS,
    SimulatedRunPlayer,
    auto_select_template,
    resolve_story_key,
    run_simulation,
)

FAST_SPEED = 5000.0  # every paced sleep < MIN_SLEEP_SECONDS -> instant

CHURN_MISSION = "Analyze why our churn spiked in Q3 and recommend 3 fixes"
SUPPORT_MISSION = "Our support tickets keep piling up - triage the queue and fix the SLA"
MARKETING_MISSION = "Which marketing channels deserve more budget? Compare spend efficiency."
ECOMMERCE_MISSION = "Diagnose revenue by category and channel for our ecommerce store and check returns"


# ── envelope validity ────────────────────────────────────────────────────


async def test_simulation_emits_valid_pinned_envelope_sequence() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED, run_id="sim-test-1")
    assert events, "a simulated run must emit events"

    # seq: starts at 1, strictly increasing, no gaps
    seqs = [e["seq"] for e in events]
    assert seqs[0] == 1
    assert seqs == list(range(1, len(events) + 1))

    # envelope: every event validates against the pinned model
    for event in events:
        validate_event(event)
        assert event["run_id"] == "sim-test-1"
        assert event["agent"] is None or event["agent"] in AGENT_ROLES
        assert event["type"] in EVENT_TYPES

    # terminal events
    assert events[0]["type"] == "run_started"
    assert events[-1]["type"] == "run_finished"
    assert events[-1]["payload"]["report_ready"] is True


async def test_simulation_honesty_labels_present() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED)
    run_started = events[0]
    assert run_started["payload"]["simulated"] is True
    assert run_started["payload"]["mode"] == "demo"
    artifacts = [e for e in events if e["type"] == "artifact_created"]
    assert artifacts, "simulated run must produce artifacts"
    for artifact in artifacts:
        assert artifact["payload"]["simulated"] is True


# ── plan / per-subtask structure ─────────────────────────────────────────


async def test_plan_created_payload_matches_pinned_shape() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED)
    plan_event = next(e for e in events if e["type"] == "plan_created")
    subtasks = plan_event["payload"]["subtasks"]
    assert len(subtasks) >= 5
    ids = {s["id"] for s in subtasks}
    assert len(ids) == len(subtasks)  # unique ids
    for subtask in subtasks:
        assert set(subtask) >= {"id", "title", "agent", "depends_on", "status"}
        assert subtask["agent"] in AGENT_ROLES
        assert subtask["status"] == "pending"
        for dep in subtask["depends_on"]:
            assert dep in ids
    assert plan_event["agent"] == "planner"


async def test_every_subtask_gets_full_lifecycle() -> None:
    events = await run_simulation(SUPPORT_MISSION, speed=FAST_SPEED)
    plan_event = next(e for e in events if e["type"] == "plan_created")
    plan_ids = [s["id"] for s in plan_event["payload"]["subtasks"]]

    started = [e["payload"]["subtask_id"] for e in events if e["type"] == "agent_started"]
    finished = [e["payload"]["subtask_id"] for e in events if e["type"] == "agent_finished"]
    stepped = [e["payload"]["subtask_id"] for e in events if e["type"] == "step_completed"]
    assert started == plan_ids
    assert stepped == plan_ids
    assert finished == plan_ids

    # agent_started strictly precedes its agent_finished in stream order
    first_start = {e["payload"]["subtask_id"]: i for i, e in enumerate(events)
                   if e["type"] == "agent_started"}
    for i, e in enumerate(events):
        if e["type"] == "agent_finished":
            assert first_start[e["payload"]["subtask_id"]] < i


async def test_tool_call_result_pairs_and_thoughts() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED)
    calls = [e for e in events if e["type"] == "tool_call"]
    results = [e for e in events if e["type"] == "tool_result"]
    assert calls, "agents must call tools"
    assert len(calls) == len(results)
    for call, result in zip(calls, results):
        assert call["agent"] == result["agent"]
        assert call["payload"]["tool"] == result["payload"]["tool"]
        assert call["payload"]["ok"] is True and result["payload"]["ok"] is True
        assert call["payload"]["args_summary"]
    thoughts = [e for e in events if e["type"] == "thought_summary"]
    assert thoughts
    for thought in thoughts:
        assert 1 <= len(thought["payload"]["summary"].split()) <= 80  # 1-2 sentences-ish


# ── artifacts: ChartSpec / TableData / report ────────────────────────────


async def test_artifacts_include_chart_table_prediction_report() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED)
    artifacts = [e["payload"] for e in events if e["type"] == "artifact_created"]
    kinds = {a["kind"] for a in artifacts}
    assert {"chart", "table", "text", "prediction", "recommendation",
            "report_markdown"} <= kinds
    assert kinds <= set(ARTIFACT_KINDS)
    for artifact in artifacts:
        assert artifact["artifact_id"]
        assert artifact["name"] and artifact["summary"]

    charts = [a for a in artifacts if a["kind"] == "chart"]
    for chart in charts:
        spec = chart["data"]
        assert {"id", "kind", "title", "x_label", "y_label", "data"} <= set(spec)
        assert spec["kind"] in {"bar", "line", "scatter", "pie"}
        assert spec["data"] and all("y" in point for point in spec["data"])
        assert "measured" in spec.get("notes", "").lower() or spec.get("notes")

    tables = [a for a in artifacts if a["kind"] == "table"]
    for table in tables:
        assert isinstance(table["data"]["columns"], list)
        assert isinstance(table["data"]["rows"], list) and table["data"]["rows"]

    report = next(a for a in artifacts if a["kind"] == "report_markdown")
    markdown = report["data"]["markdown"]
    assert "## Insights" in markdown and "## Recommendations" in markdown


async def test_measured_sample_facts_appear_in_content() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED)
    blob = json.dumps(events)
    for measured in ("24.8", "37.4", "15.5", "7.6", "13", "42"):
        assert measured in blob, f"expected measured churn fact {measured}"

    support_events = await run_simulation(SUPPORT_MISSION, speed=FAST_SPEED)
    support_blob = json.dumps(support_events)
    for measured in ("31", "25", "56", "32.5", "5.3", "7.6"):
        assert measured in support_blob, f"expected support fact {measured}"

    marketing_events = await run_simulation(MARKETING_MISSION, speed=FAST_SPEED)
    marketing_blob = json.dumps(marketing_events)
    for measured in ("1.011", "0.388", "0.321", "0.273", "0.034"):
        assert measured in marketing_blob, f"expected marketing fact {measured}"

    ecommerce_events = await run_simulation(ECOMMERCE_MISSION, speed=FAST_SPEED)
    ecommerce_blob = json.dumps(ecommerce_events)
    for measured in ("27.1", "121", "12.0", "1.8", "7.9"):
        assert measured in ecommerce_blob, f"expected ecommerce fact {measured}"


# ── token updates ────────────────────────────────────────────────────────


async def test_token_updates_are_plausible_and_cumulative() -> None:
    events = await run_simulation(CHURN_MISSION, speed=FAST_SPEED)
    token_events = [e for e in events if e["type"] == "token_update"]
    assert len(token_events) >= 5  # one per subtask
    previous_total = 0.0
    for event in token_events:
        payload = event["payload"]
        assert event["agent"] == payload["agent"]
        assert payload["agent"] in AGENT_ROLES
        assert 0 < payload["input_tokens"] < 10_000
        assert 0 < payload["output_tokens"] < 5_000
        assert payload["cost_usd"] >= 0
        assert payload["run_total_usd"] >= previous_total
        previous_total = payload["run_total_usd"]
    # cost math at default 0.11/0.11 rates: total = (in+out)/1M * 0.11
    total_in = sum(e["payload"]["input_tokens"] for e in token_events)
    total_out = sum(e["payload"]["output_tokens"] for e in token_events)
    expected_total = round((total_in + total_out) / 1_000_000 * 0.11, 6)
    # The meter rounds per-agent costs before summing, so accumulated rounding
    # can drift by up to ~5e-7 per agent vs this single-shot recomputation.
    # 1e-5 still catches any real rate/sum error (which would be orders larger).
    assert abs(token_events[-1]["payload"]["run_total_usd"] - expected_total) < 1e-5


# ── template auto-selection and story routing ────────────────────────────


def test_auto_select_template_by_keywords() -> None:
    assert auto_select_template(CHURN_MISSION) == "sales_insights_team"
    assert auto_select_template(SUPPORT_MISSION) == "support_triage_team"
    assert auto_select_template(MARKETING_MISSION) == "market_research_team"
    assert auto_select_template("hello world") in TEMPLATE_IDS  # deterministic default


def test_resolve_story_key_routes_measured_datasets() -> None:
    assert resolve_story_key("sales_insights_team", CHURN_MISSION) == "saas_churn"
    assert resolve_story_key("sales_insights_team", ECOMMERCE_MISSION) == "ecommerce_sales"
    assert resolve_story_key("support_triage_team", SUPPORT_MISSION) == "support_tickets"
    assert resolve_story_key("market_research_team", MARKETING_MISSION) == "marketing_spend"
    # mission keywords can override a template default
    assert resolve_story_key("market_research_team", CHURN_MISSION) == "saas_churn"


def test_unknown_template_id_falls_back() -> None:
    assert auto_select_template("") == "market_research_team"
    assert resolve_story_key("nonexistent_template", "") == "saas_churn"


async def test_explicit_template_id_is_respected() -> None:
    events = await run_simulation(
        "A vague mission that matches no keywords", template_id="support_triage_team",
        speed=FAST_SPEED,
    )
    assert events[0]["payload"]["template_id"] == "support_triage_team"
    assert events[0]["payload"]["story"] == "support_tickets"


# ── determinism ──────────────────────────────────────────────────────────


async def test_content_is_deterministic_across_runs() -> None:
    def fingerprint(events: list[dict]) -> list[tuple]:
        return [
            (e["type"], e["agent"], json.dumps(e["payload"], sort_keys=True))
            for e in events
        ]

    first = await run_simulation(CHURN_MISSION, speed=FAST_SPEED, run_id="run-a")
    second = await run_simulation(CHURN_MISSION, speed=FAST_SPEED, run_id="run-b")
    assert fingerprint(first) == fingerprint(second)
    assert [e["run_id"] for e in first] == ["run-a"] * len(first)


async def test_on_event_receives_same_events_as_returned() -> None:
    seen: list[dict] = []
    returned = await run_simulation(
        CHURN_MISSION, on_event=seen.append, speed=FAST_SPEED, run_id="run-cb"
    )
    assert seen == returned


async def test_bad_on_event_sink_does_not_crash_the_run() -> None:
    def bad_sink(_event: dict) -> None:
        raise RuntimeError("sink exploded")

    events = await run_simulation(CHURN_MISSION, on_event=bad_sink, speed=FAST_SPEED)
    assert events[-1]["type"] == "run_finished"


# ── runner-compatible construction ───────────────────────────────────────


async def test_player_accepts_runner_kwargs_and_template_dag() -> None:
    template = {
        "id": "sales_insights_team",
        "expected_dag": [
            {"id": "t1", "title": "Frame it", "agent": "planner", "depends_on": []},
            {"id": "t2", "title": "Analyze it", "agent": "analyst", "depends_on": ["t1"]},
            {"id": "t3", "title": "Review it", "agent": "critic", "depends_on": ["t2"]},
        ],
    }
    player = SimulatedRunPlayer(
        run_id="run-kw",
        mission_text=CHURN_MISSION,  # runner passes mission_text
        template=template,
        template_id=None,
        dataset_path="data/samples/saas_churn.csv",
        dataset_columns=["plan", "logins_last_30d", "is_churned"],
        dataset_info={"row_count": 2000, "columns": ["plan", "logins_last_30d", "is_churned"]},
        speed=FAST_SPEED,
    )
    assert player.run_id == "run-kw"
    assert player.template_id == "sales_insights_team"
    assert [s["id"] for s in player.plan] == ["t1", "t2", "t3"]
    events = await player.play()
    assert events[-1]["type"] == "run_finished"
    assert any(e["payload"].get("path") == "data/samples/saas_churn.csv"
               for e in events if e["type"] == "artifact_created")


async def test_player_requires_a_mission() -> None:
    with pytest.raises(ValueError):
        SimulatedRunPlayer(mission="   ")


# ── pacing design (cheap static check, no slow sleeps) ───────────────────


def test_pacing_design_targets_25_45_seconds_at_1x() -> None:
    """The canonical 6-subtask plan should take ~25-45s at speed=1.0."""
    # Canonical run shape: 2 bookends + 6 subtasks; analyst/critic carry 2 tools.
    subtask_delays = {
        "planner": (1, 0), "researcher": (1, 1), "analyst": (2, 1),
        "forecaster": (1, 1), "critic": (1, 2),
    }  # agent -> (subtask count, artifact count); tools: 2 per analyst subtask, else 1
    total = BASE_DELAYS["run_started"] + BASE_DELAYS["plan_created"] + BASE_DELAYS["pre_finish"]
    for agent, (subtasks, artifacts) in subtask_delays.items():
        for _ in range(subtasks):
            total += BASE_DELAYS["agent_started"] + BASE_DELAYS["thought_summary"]
            tool_pairs = 2 if agent == "analyst" else 1
            total += tool_pairs * (BASE_DELAYS["tool_call"] + BASE_DELAYS["tool_result"])
            total += artifacts * BASE_DELAYS["artifact_created"]
            artifacts = 0  # only the first subtask of the critic carries 2 artifacts
            total += BASE_DELAYS["step_completed"] + BASE_DELAYS["agent_finished"]
            total += BASE_DELAYS["token_update"] + BASE_DELAYS["inter_subtask"]
    assert 25 <= total <= 45, f"designed pacing is {total:.1f}s at 1x"
