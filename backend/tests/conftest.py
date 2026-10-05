"""Shared fixtures for the AgentForge backend test suite.

The environment is pinned BEFORE importing the app so config/engine creation
see deterministic values. The TestClient fixture is session-scoped AND used as
a context manager: that keeps one event-loop portal alive for the whole session,
which is what lets background run tasks keep executing between requests.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import time
from typing import Any, Iterator

import pytest

_TEST_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="agentforge_backend_tests_"))
(_TEST_ROOT / "uploads").mkdir(parents=True, exist_ok=True)
(_TEST_ROOT / "reports").mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'test.sqlite3').as_posix()}"
os.environ["UPLOAD_DIR"] = (_TEST_ROOT / "uploads").as_posix()
os.environ["REPORT_DIR"] = (_TEST_ROOT / "reports").as_posix()
os.environ["RUN_MODE"] = "demo"
os.environ["DEMO_RUN_SPEED"] = "200"  # instant scripted runs; product default is 1.0
os.environ["API_KEY"] = ""
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["LLM_MODE"] = "mock"
os.environ["MAX_UPLOAD_MB"] = "5"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.main import app  # noqa: E402

TERMINAL_STATUSES = {"succeeded", "failed", "partial"}


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def override_settings():
    """Install a dependency override for ``app.config.get_settings``."""

    def _apply(**kwargs: Any) -> Settings:
        settings = Settings(**kwargs)
        app.dependency_overrides[get_settings] = lambda: settings
        return settings

    yield _apply
    app.dependency_overrides.pop(get_settings, None)


# ── helpers (importable by test modules) ────────────────────────────────


def create_mission(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    """POST a mission and return its JSON."""
    payload: dict[str, Any] = {
        "goal": kwargs.pop("goal", "Analyze why churn spiked in Q3 and recommend 3 fixes")
    }
    payload.update(kwargs)
    response = client.post("/api/missions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def start_run(client: TestClient, mission_id: str) -> str:
    """POST a run for a mission and return the run id."""
    response = client.post(f"/api/missions/{mission_id}/runs", json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def wait_for_terminal(client: TestClient, run_id: str, timeout: float = 30.0) -> str:
    """Poll GET /api/runs/{id} until the run reaches a terminal status."""
    deadline = time.monotonic() + timeout
    last_status: str | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        last_status = response.json()["run"]["status"]
        if last_status in TERMINAL_STATUSES:
            return last_status
        time.sleep(0.05)
    raise AssertionError(
        f"Run {run_id} did not reach a terminal state (last={last_status})"
    )


@pytest.fixture(scope="session")
def demo_run(client: TestClient) -> dict[str, Any]:
    """One finished demo run, shared by several test modules."""
    mission = create_mission(client, goal="Session demo mission: shared fixture run")
    run_id = start_run(client, mission["id"])
    status = wait_for_terminal(client, run_id)
    assert status == "succeeded", status
    return {"mission_id": mission["id"], "run_id": run_id}
