"""POST /api/upload: happy path, validation, caps, disk persistence."""

from __future__ import annotations


import pathlib
from conftest import create_mission, start_run, wait_for_terminal
from fastapi.testclient import TestClient

CSV_BYTES = (
    b"month,region,units,revenue\n"
    b"2026-01,west,120,4800.50\n"
    b"2026-01,east,80,3100.00\n"
    b"2026-02,west,150,6000.75\n"
    b"2026-02,east,90,3550.25\n"
    b"2026-03,west,170,6800.00\n"
)


def test_upload_csv_happy_path(client: TestClient) -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("sales.csv", CSV_BYTES, "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["filename"] == "sales.csv"
    assert body["row_count"] == 5
    assert body["columns"] == ["month", "region", "units", "revenue"]
    assert body["dtypes"]["units"] == "integer"
    assert body["dtypes"]["revenue"] == "float"
    assert len(body["preview"]) == 5  # <= 20 rows
    assert body["preview"][0] == ["2026-01", "west", "120", "4800.50"]
    assert isinstance(body["quality_notes"], list)


def test_upload_persists_bytes_to_upload_dir(client: TestClient) -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("persist_me.csv", CSV_BYTES, "text/csv")},
    )
    dataset = response.json()
    from app.config import get_settings

    settings = get_settings()
    stored = pathlib.Path(settings.upload_dir) / f"{dataset['id']}.csv"
    assert stored.exists()
    assert stored.read_bytes() == CSV_BYTES


def test_upload_rejects_non_csv_415(client: TestClient) -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("data.xlsx", b"not a csv", "application/vnd.ms-excel")},
    )
    assert response.status_code == 415
    assert ".csv" in response.json()["detail"]


def test_upload_rejects_oversize_413(client: TestClient, override_settings) -> None:
    override_settings(max_upload_mb=0.001)  # ~1048 bytes
    big = b"col1,col2\n" + (b"1,2\n" * 500)  # ~2.5KB
    response = client.post(
        "/api/upload",
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert response.status_code == 413
    assert "MAX_UPLOAD_MB" in response.json()["detail"]


def test_upload_oversize_uses_env_cap(client: TestClient, override_settings) -> None:
    override_settings(max_upload_mb=5)
    response = client.post(
        "/api/upload",
        files={"file": ("ok.csv", CSV_BYTES, "text/csv")},
    )
    assert response.status_code == 201


def test_upload_empty_file_422(client: TestClient) -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 422


def test_upload_no_file_field_422(client: TestClient) -> None:
    response = client.post("/api/upload", data={})
    assert response.status_code == 422


def test_upload_headers_only_csv_ok(client: TestClient) -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("headers_only.csv", b"col_a,col_b\n", "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["row_count"] == 0
    assert body["columns"] == ["col_a", "col_b"]
    assert any("small" in note.lower() for note in body["quality_notes"])


def test_uploaded_dataset_feeds_a_demo_run(client: TestClient) -> None:
    upload = client.post(
        "/api/upload",
        files={"file": ("churn.csv", CSV_BYTES, "text/csv")},
    )
    dataset_id = upload.json()["id"]
    mission = create_mission(client, goal="Explain the revenue trend", dataset_id=dataset_id)
    run_id = start_run(client, mission["id"])
    assert wait_for_terminal(client, run_id) == "succeeded"

    snapshot = client.get(f"/api/runs/{run_id}").json()
    kinds = {a["kind"] for a in snapshot["artifacts"]}
    assert "table" in kinds, f"analyst should emit a table artifact, got {kinds}"
    # The uploaded CSV must actually feed the run: the insight engine turns the
    # analyst artifacts into a report whose insights cite run artifacts.
    report = snapshot["report"]
    insights = report["insights"]
    assert insights, "report should contain insights derived from the run artifacts"
    assert all(i.get("evidence") for i in insights), "every insight must cite evidence"
    assert all(i.get("strength") in ("high", "medium", "low") for i in insights)
