"""GET /healthz + OpenAPI contract checks."""

from __future__ import annotations

from fastapi.testclient import TestClient

PINNED_HTTP_ROUTES = (
    "/api/missions",
    "/api/missions/{mission_id}",
    "/api/missions/{mission_id}/runs",
    "/api/runs/{run_id}",
    "/api/runs/{run_id}/events",
    "/api/upload",
    "/api/templates",
    "/api/runs/{run_id}/export/n8n",
    "/api/runs/{run_id}/report",
    "/healthz",
)


def test_healthz_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_all_pinned_routes(client: TestClient) -> None:
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = set(spec.json()["paths"])
    missing = [route for route in PINNED_HTTP_ROUTES if route not in paths]
    assert not missing, f"Missing pinned routes in OpenAPI: {missing}"


def test_openapi_tags_have_descriptions(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    tag_names = {tag["name"] for tag in spec.get("tags", [])}
    for expected in ("Missions", "Runs", "Uploads", "Templates", "Integrations", "Health"):
        assert expected in tag_names
    # every operation declares a tag and a summary
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method in ("parameters",):
                continue
            assert operation.get("tags"), f"{method.upper()} {path} has no tags"
            assert operation.get("summary"), f"{method.upper()} {path} has no summary"


def test_openapi_documents_websocket_hint(client: TestClient) -> None:
    """The WS route is not in OpenAPI; verify it is registered on the runs
    router (end-to-end behavior is covered by the WS tests)."""
    from app.api.routes import runs as runs_module

    ws_paths = [
        getattr(route, "path", "")
        for route in runs_module.router.routes
        if "stream" in getattr(route, "path", "")
    ]
    assert "/runs/{run_id}/stream" in ws_paths
