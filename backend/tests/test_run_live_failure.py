"""RUN_MODE=live without the orchestrator: run must FAIL with a clear
run_failed event — success is never faked."""

from __future__ import annotations

import sys

from conftest import create_mission, start_run, wait_for_terminal
from fastapi.testclient import TestClient


def test_live_run_fails_when_orchestrator_missing(
    client: TestClient, override_settings, monkeypatch
) -> None:
    override_settings(run_mode="live")
    # Make `from orchestrator.engine import execute_run` raise ImportError even
    # if the package landed mid-flight (None in sys.modules blocks the import).
    monkeypatch.setitem(sys.modules, "orchestrator", None)

    mission = create_mission(client, goal="Live mode without orchestrator mission")
    run_id = start_run(client, mission["id"])
    status = wait_for_terminal(client, run_id)

    assert status == "failed"
    snapshot = client.get(f"/api/runs/{run_id}").json()
    assert snapshot["run"]["status"] == "failed"
    assert snapshot["run"]["error_stage"] == "startup"
    assert "orchestrator" in (snapshot["run"]["error"] or "")
    assert snapshot["report"] is None
    assert snapshot["run"]["finished_at"] is not None

    failed_events = [e for e in snapshot["events"] if e["type"] == "run_failed"]
    assert failed_events, "run_failed event must be emitted"
    payload = failed_events[-1]["payload"]
    assert payload["stage"] == "startup"
    assert "orchestrator" in payload["error"]
    # token usage present (zeroed) — no fabricated usage
    assert snapshot["token_usage"]["totals"]["cost_usd"] == 0.0


def test_live_run_fails_when_engine_module_missing(
    client: TestClient, override_settings, monkeypatch
) -> None:
    """Same contract when `orchestrator` imports but `orchestrator.engine` does not."""
    override_settings(run_mode="live")
    monkeypatch.setitem(sys.modules, "orchestrator.engine", None)

    mission = create_mission(client, goal="Live mode missing engine module")
    run_id = start_run(client, mission["id"])
    status = wait_for_terminal(client, run_id)
    assert status == "failed"
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["run"]["error_stage"] == "startup"
