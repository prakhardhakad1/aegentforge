"""Integration routes: n8n export + report downloads (501 / 200 / 404 paths).

Cross-agent modules are pinned in both directions with sys.modules tricks so
the tests are deterministic whether or not the other agents' code has landed.
"""

from __future__ import annotations

import sys
import types

import pytest
from conftest import demo_run
from fastapi.testclient import TestClient

_ = demo_run  # session fixture reference

N8N_MODULE = "integrations.n8n_export"
REPORT_MODULE = "orchestrator.report"


def _install_fake_n8n(monkeypatch) -> None:
    fake = types.ModuleType(N8N_MODULE)

    def export_n8n(snapshot: dict) -> dict:
        return {
            "name": f"AgentForge run {snapshot['run']['id']}",
            "nodes": [
                {"name": "Start", "type": "n8n-nodes-base.webhook"},
                {"name": "Report", "type": "n8n-nodes-base.httpRequest"},
            ],
            "connections": {"Start": {"main": [[{"node": "Report", "type": "main"}]]}},
        }

    fake.export_n8n = export_n8n
    monkeypatch.setitem(sys.modules, N8N_MODULE, fake)


def _install_fake_report(monkeypatch) -> None:
    fake = types.ModuleType(REPORT_MODULE)

    def render_markdown(report: dict) -> str:
        return f"# {report.get('title', 'Report')}\n\nSimulated markdown body.\n"

    def export_pdf(report_or_markdown, out_path: str):
        from pathlib import Path

        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n%fake-test-pdf\n%%EOF\n")
        return path

    fake.render_markdown = render_markdown
    fake.export_pdf = export_pdf
    monkeypatch.setitem(sys.modules, REPORT_MODULE, fake)


# ── n8n export ──────────────────────────────────────────────────────────


def test_export_501_when_module_missing(client: TestClient, demo_run, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, N8N_MODULE, None)
    response = client.post(f"/api/runs/{demo_run['run_id']}/export/n8n")
    assert response.status_code == 501
    body = response.json()
    assert body["status_code"] == 501
    assert "not available" in body["detail"]


def test_export_200_with_module(client: TestClient, demo_run, monkeypatch) -> None:
    _install_fake_n8n(monkeypatch)
    response = client.post(f"/api/runs/{demo_run['run_id']}/export/n8n")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    workflow = response.json()
    assert workflow["nodes"]
    assert demo_run["run_id"] in workflow["name"]


def test_export_500_when_module_raises(
    client: TestClient, demo_run, monkeypatch
) -> None:
    fake = types.ModuleType(N8N_MODULE)

    def export_n8n(snapshot: dict) -> dict:
        raise ValueError("bad snapshot")

    fake.export_n8n = export_n8n
    monkeypatch.setitem(sys.modules, N8N_MODULE, fake)
    response = client.post(f"/api/runs/{demo_run['run_id']}/export/n8n")
    assert response.status_code == 500
    assert "n8n export failed" in response.json()["detail"]


def test_export_404_unknown_run_with_module(client: TestClient, monkeypatch) -> None:
    _install_fake_n8n(monkeypatch)
    response = client.post("/api/runs/missing-run/export/n8n")
    assert response.status_code == 404


# ── report downloads ────────────────────────────────────────────────────


def test_report_markdown_501_when_module_missing(
    client: TestClient, demo_run, monkeypatch
) -> None:
    monkeypatch.setitem(sys.modules, REPORT_MODULE, None)
    response = client.get(f"/api/runs/{demo_run['run_id']}/report")
    assert response.status_code == 501
    body = response.json()
    assert body["status_code"] == 501
    assert "orchestrator.report" in body["detail"]


def test_report_markdown_200_with_module(
    client: TestClient, demo_run, monkeypatch
) -> None:
    _install_fake_report(monkeypatch)
    response = client.get(f"/api/runs/{demo_run['run_id']}/report")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert "Simulated markdown body" in response.text


def test_report_pdf_200_with_module(
    client: TestClient, demo_run, monkeypatch
) -> None:
    _install_fake_report(monkeypatch)
    response = client.get(
        f"/api/runs/{demo_run['run_id']}/report", params={"format": "pdf"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_report_invalid_format_422(client: TestClient, demo_run) -> None:
    response = client.get(
        f"/api/runs/{demo_run['run_id']}/report", params={"format": "docx"}
    )
    assert response.status_code == 422


def test_report_404_unknown_run(client: TestClient, monkeypatch) -> None:
    _install_fake_report(monkeypatch)
    response = client.get("/api/runs/missing-run/report")
    assert response.status_code == 404


def test_report_404_when_run_has_no_report(
    client: TestClient, override_settings, monkeypatch
) -> None:
    override_settings(run_mode="live")
    monkeypatch.setitem(sys.modules, "orchestrator", None)
    from conftest import create_mission, start_run, wait_for_terminal

    mission = create_mission(client, goal="No report 404 mission")
    run_id = start_run(client, mission["id"])
    assert wait_for_terminal(client, run_id) == "failed"
    _install_fake_report(monkeypatch)
    response = client.get(f"/api/runs/{run_id}/report")
    assert response.status_code == 404
    assert "not ready" in response.json()["detail"]


def test_report_uses_real_renderer_when_available(client: TestClient, demo_run) -> None:
    """Soft integration check: when Agent 6's orchestrator.report is installed,
    the markdown download must work end-to-end."""
    try:
        import orchestrator.report  # noqa: F401
    except Exception:
        pytest.skip("orchestrator.report not installed yet")
    response = client.get(f"/api/runs/{demo_run['run_id']}/report")
    assert response.status_code == 200
    assert response.text.lstrip().startswith("#")
