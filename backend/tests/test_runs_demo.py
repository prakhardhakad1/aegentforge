"""Demo-mode run lifecycle: POST runs, snapshot, event log, artifacts, report."""

from __future__ import annotations

from typing import Any

from conftest import (
    create_mission,
    demo_run,
    start_run,
    wait_for_terminal,  # noqa: F401 (fixture-style import kept for clarity)
)
from fastapi.testclient import TestClient

from app.schemas.common import EVENT_TYPES

_ = demo_run  # session fixture; referenced so linters keep the import


def test_create_run_returns_queued(client: TestClient) -> None:
    mission = create_mission(client, goal="Queued status mission")
    run_id = start_run(client, mission["id"])
    snapshot: dict[str, Any] = client.get(f"/api/runs/{run_id}").json()
    assert snapshot["run"]["status"] in ("queued", "running", "succeeded")
    assert snapshot["run"]["mission_id"] == mission["id"]
    assert snapshot["run"]["mode"] == "demo"


def test_run_reaches_succeeded_with_full_snapshot(client: TestClient) -> None:
    mission = create_mission(client, goal="Full lifecycle mission")
    run_id = start_run(client, mission["id"])
    status = wait_for_terminal(client, run_id)
    assert status == "succeeded"

    snapshot = client.get(f"/api/runs/{run_id}").json()
    run = snapshot["run"]
    assert run["status"] == "succeeded"
    assert run["finished_at"] is not None

    # mission embedded
    assert snapshot["mission"]["id"] == mission["id"]

    # events: pinned envelope, seq strictly increasing from 1
    events = snapshot["events"]
    assert events, "run must produce events"
    seqs = [event["seq"] for event in events]
    assert seqs[0] == 1
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    for event in events:
        assert event["type"] in EVENT_TYPES or event["type"] == "unknown"
        assert event["run_id"] == run_id
        assert event["ts"].endswith("Z")
        assert event["agent"] is None or isinstance(event["agent"], str)
        assert isinstance(event["payload"], dict)
    types = {event["type"] for event in events}
    assert {"run_started", "plan_created", "agent_started", "run_finished"} <= types

    # plan_created payload shape
    plan_event = next(e for e in events if e["type"] == "plan_created")
    subtasks = plan_event["payload"]["subtasks"]
    assert subtasks and all({"id", "title", "agent", "depends_on"} <= set(s) for s in subtasks)

    # artifacts persisted
    for artifact in snapshot["artifacts"]:
        assert artifact["run_id"] == run_id
        assert artifact["kind"]
        assert artifact["payload"]

    # token usage assembled from token_update events
    usage = snapshot["token_usage"]
    assert usage["totals"]["input_tokens"] > 0
    assert usage["totals"]["output_tokens"] > 0
    assert usage["totals"]["cost_usd"] > 0
    assert usage["per_agent"], "per-agent meter must be populated"
    assert set(usage["per_agent"]) <= {"planner", "researcher", "analyst", "forecaster", "critic"}

    # report attached (demo fallback produces one)
    report = snapshot["report"]
    assert report is not None
    for key in ("title", "mission", "style", "executive_summary", "insights",
                "charts", "predictions", "recommendations", "appendix"):
        assert key in report
    assert report["mission"] == mission["goal"]


def test_events_polling_with_after_seq(client: TestClient) -> None:
    mission = create_mission(client, goal="Polling mission")
    run_id = start_run(client, mission["id"])
    wait_for_terminal(client, run_id)

    all_events = client.get(f"/api/runs/{run_id}/events").json()["events"]
    assert all_events[0]["seq"] == 1

    sliced = client.get(
        f"/api/runs/{run_id}/events", params={"after_seq": 2}
    ).json()["events"]
    assert all(event["seq"] > 2 for event in sliced)
    assert len(sliced) == len(all_events) - 2


def test_events_404_for_unknown_run(client: TestClient) -> None:
    assert client.get("/api/runs/nope/events").status_code == 404


def test_run_snapshot_404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/api/runs/nope")
    assert response.status_code == 404


def test_run_for_unknown_mission_404(client: TestClient) -> None:
    response = client.post("/api/missions/nope/runs", json={})
    assert response.status_code == 404


def test_run_with_unknown_template_override_404(client: TestClient) -> None:
    mission = create_mission(client, goal="Bad template override mission")
    response = client.post(
        f"/api/missions/{mission['id']}/runs", json={"template_id": "missing_team"}
    )
    assert response.status_code == 404


def test_run_uses_mission_template(client: TestClient) -> None:
    mission = create_mission(
        client, goal="Template-bound mission", template_id="sales_insights_team"
    )
    run_id = start_run(client, mission["id"])
    wait_for_terminal(client, run_id)
    snapshot = client.get(f"/api/runs/{run_id}").json()
    assert snapshot["run"]["template_id"] == "sales_insights_team"
    plan_event = next(
        e for e in snapshot["events"] if e["type"] == "plan_created"
    )
    agents = {s["agent"] for s in plan_event["payload"]["subtasks"]}
    assert agents <= {"planner", "researcher", "analyst", "forecaster", "critic"}


def test_run_accepts_empty_and_absent_body(client: TestClient) -> None:
    mission = create_mission(client, goal="Body shape mission")
    response_no_body = client.post(f"/api/missions/{mission['id']}/runs")
    assert response_no_body.status_code == 201
    response_empty = client.post(f"/api/missions/{mission['id']}/runs", json={})
    assert response_empty.status_code == 201


def test_finished_run_report_not_ready_without_report(client: TestClient) -> None:
    """A finished run whose report is missing -> report route 404 (not fake)."""
    # Craft a run row with no report directly (live failure path is covered
    # elsewhere); here we verify the 404 contract for missing reports.
    from app.db.base import session_scope
    from app.models import Mission, Run, new_uuid

    with session_scope() as db:
        mission = Mission(id=new_uuid(), goal="No-report mission")
        run = Run(id=new_uuid(), mission_id=mission.id, status="succeeded")
        db.add_all([mission, run])
        db.commit()
        run_id = run.id

    response = client.get(f"/api/runs/{run_id}/report")
    assert response.status_code == 404
    assert "not ready" in response.json()["detail"]
