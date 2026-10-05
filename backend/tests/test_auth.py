"""Auth contract: X-API-Key enforced ONLY when API_KEY env is set."""

from __future__ import annotations

from conftest import create_mission
from fastapi.testclient import TestClient


def test_guest_mode_allows_requests_without_key(client: TestClient) -> None:
    """Default test env has API_KEY='' -> guest mode."""
    mission = create_mission(client, goal="Guest mode mission")
    assert mission["id"]
    assert client.get("/api/templates").status_code == 200


def test_healthz_never_requires_auth(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_auth_required_when_api_key_set(
    client: TestClient, override_settings
) -> None:
    override_settings(api_key="sekrit-demo-key")

    # no header -> 401
    response = client.post("/api/missions", json={"goal": "x"})
    assert response.status_code == 401
    assert response.json()["status_code"] == 401

    # wrong header -> 401
    response = client.post(
        "/api/missions",
        json={"goal": "x"},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401

    # correct header -> 201
    response = client.post(
        "/api/missions",
        json={"goal": "authed mission"},
        headers={"X-API-Key": "sekrit-demo-key"},
    )
    assert response.status_code == 201

    # every other protected route honors it too
    assert (
        client.get("/api/templates", headers={"X-API-Key": "sekrit-demo-key"}).status_code
        == 200
    )
    assert client.get("/api/templates").status_code == 401
    assert client.get("/api/missions").status_code == 401
    assert client.get("/api/runs/some-id").status_code == 401
    assert client.get("/api/runs/some-id/events").status_code == 401
    assert client.post("/api/runs/some-id/export/n8n").status_code == 401


def test_auth_case_insensitive_header_name(
    client: TestClient, override_settings
) -> None:
    override_settings(api_key="another-key")
    response = client.post(
        "/api/missions",
        json={"goal": "lowercase header"},
        headers={"x-api-key": "another-key"},
    )
    assert response.status_code == 201
