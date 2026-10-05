"""Mission routes: POST /api/missions, GET /api/missions, GET /api/missions/{id}."""

from __future__ import annotations

from typing import Any

from conftest import create_mission
from fastapi.testclient import TestClient


def test_create_mission_minimal(client: TestClient) -> None:
    mission = create_mission(client, goal="Analyze why churn spiked in Q3")
    assert mission["id"]
    assert mission["goal"] == "Analyze why churn spiked in Q3"
    assert mission["template_id"] is None
    assert mission["dataset_id"] is None
    assert mission["created_at"]


def test_create_mission_with_template(client: TestClient) -> None:
    mission = create_mission(client, goal="Market scan", template_id="market_research_team")
    assert mission["template_id"] == "market_research_team"


def test_create_mission_unknown_template_404(client: TestClient) -> None:
    response = client.post(
        "/api/missions", json={"goal": "x", "template_id": "no_such_team"}
    )
    assert response.status_code == 404
    assert "no_such_team" in response.json()["detail"]


def test_create_mission_unknown_dataset_404(client: TestClient) -> None:
    response = client.post(
        "/api/missions", json={"goal": "x", "dataset_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert response.status_code == 404


def test_create_mission_blank_goal_422(client: TestClient) -> None:
    response = client.post("/api/missions", json={"goal": "   "})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_create_mission_missing_goal_422(client: TestClient) -> None:
    response = client.post("/api/missions", json={})
    assert response.status_code == 422


def test_create_mission_overlong_goal_422(client: TestClient) -> None:
    response = client.post("/api/missions", json={"goal": "x" * 8001})
    assert response.status_code == 422


def test_get_mission_roundtrip(client: TestClient) -> None:
    created = create_mission(client, goal="Round trip mission")
    fetched = client.get(f"/api/missions/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["goal"] == "Round trip mission"


def test_get_mission_missing_404(client: TestClient) -> None:
    response = client.get("/api/missions/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "http_error"
    assert "not found" in body["detail"]


def test_list_missions_pagination(client: TestClient) -> None:
    created = [
        create_mission(client, goal=f"Pagination mission {index}")
        for index in range(3)
    ]
    response = client.get("/api/missions", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 3
    assert len(body["missions"]) == 2

    page2 = client.get("/api/missions", params={"limit": 2, "offset": 2}).json()
    ids_page1 = {m["id"] for m in body["missions"]}
    ids_page2 = {m["id"] for m in page2["missions"]}
    assert not (ids_page1 & ids_page2)
    assert created[0]["id"] in {m["id"] for m in client.get("/api/missions").json()["missions"]}


def test_list_missions_limit_bounds(client: TestClient) -> None:
    assert client.get("/api/missions", params={"limit": 0}).status_code == 422
    assert client.get("/api/missions", params={"limit": 201}).status_code == 422
    assert client.get("/api/missions", params={"offset": -1}).status_code == 422


def test_mission_with_dataset_link(client: TestClient) -> None:
    csv_content = "region,units\nwest,120\neast,80\n"
    upload = client.post(
        "/api/upload",
        files={"file": ("regions.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert upload.status_code == 201, upload.text
    dataset_id = upload.json()["id"]
    mission = create_mission(client, goal="Use dataset", dataset_id=dataset_id)
    assert mission["dataset_id"] == dataset_id
    fetched: dict[str, Any] = client.get(f"/api/missions/{mission['id']}").json()
    assert fetched["dataset_id"] == dataset_id
