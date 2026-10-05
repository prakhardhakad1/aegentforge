"""Integration routes: POST /api/runs/{id}/export/n8n and
GET /api/runs/{id}/report?format=markdown|pdf.

Both features are owned by other agents (Agent 9: n8n export; Agent 6:
orchestrator.report). When their modules are not importable yet, the routes
return **501 with a clear JSON error** — success is never faked.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.config import Settings, get_settings
from app.models import Run
from app.services.snapshot import build_run_snapshot

logger = logging.getLogger("agentforge.integrations")

router = APIRouter(
    tags=["Integrations"],
    dependencies=[Depends(require_api_key)],
)

N8N_UNAVAILABLE_DETAIL = (
    "n8n export is not available yet: the 'integrations.n8n_export' module "
    "(Agent 9) could not be imported. No export was faked."
)
REPORT_UNAVAILABLE_DETAIL = (
    "Report rendering is not available yet: the 'orchestrator.report' module "
    "(Agent 6) could not be imported. No rendering was faked."
)


@router.post(
    "/runs/{run_id}/export/n8n",
    response_class=Response,
    summary="Export a run as an n8n workflow",
    description=(
        "Converts the run snapshot (GET /api/runs/{id} shape) into an "
        "importable n8n workflow JSON, returned as an attachment. Returns 501 "
        "while integrations.n8n_export is unavailable."
    ),
)
def export_run_n8n(run_id: str, db: Session = Depends(get_db)) -> Response:
    del db  # run existence is checked via the snapshot builder
    snapshot = build_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    try:
        from integrations.n8n_export import export_n8n
    except Exception as exc:  # ImportError or a broken half-landed module
        logger.info("n8n export unavailable for run %s: %s", run_id, exc)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{N8N_UNAVAILABLE_DETAIL} ({type(exc).__name__}: {exc})",
        ) from exc

    try:
        workflow = export_n8n(snapshot)
    except Exception as exc:  # noqa: BLE001 - surface integration failures
        logger.exception("export_n8n failed for run %s", run_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"n8n export failed: {type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(workflow, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="n8n export returned a non-dict payload",
        )
    body = json.dumps(workflow, indent=2, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="n8n_workflow_{run_id}.json"'
        },
    )


@router.get(
    "/runs/{run_id}/report",
    summary="Download the run report",
    description=(
        "Downloads the finished run's report as ``markdown`` (default) or "
        "``pdf``. 404 when the run/report does not exist yet, 501 while "
        "orchestrator.report is unavailable."
    ),
)
def download_report(
    run_id: str,
    format: Literal["markdown", "pdf"] = Query(default="markdown"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> Response:
    del db  # existence checked via the run row below
    from app.db.base import session_scope

    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run '{run_id}' not found",
            )
        report = run.report_json

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Report for run '{run_id}' is not ready yet (the run has not "
                "finished with a report)."
            ),
        )

    if format == "markdown":
        return _markdown_response(run_id, report)
    return _pdf_response(run_id, report, settings)


def _markdown_response(run_id: str, report: dict) -> Response:
    try:
        from orchestrator.report import render_markdown
    except Exception as exc:  # ImportError or broken half-landed module
        logger.info("Report markdown rendering unavailable for run %s: %s", run_id, exc)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{REPORT_UNAVAILABLE_DETAIL} ({type(exc).__name__}: {exc})",
        ) from exc

    try:
        markdown_text = render_markdown(report)
    except Exception as exc:  # noqa: BLE001
        logger.exception("render_markdown failed for run %s", run_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report rendering failed: {type(exc).__name__}: {exc}",
        ) from exc

    if not isinstance(markdown_text, str):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="render_markdown returned a non-string payload",
        )
    return Response(
        content=markdown_text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="report_{run_id}.md"'
        },
    )


def _pdf_response(run_id: str, report: dict, settings: Settings) -> Response:
    try:
        from orchestrator.report import export_pdf
    except Exception as exc:  # ImportError or broken half-landed module
        logger.info("Report PDF export unavailable for run %s: %s", run_id, exc)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{REPORT_UNAVAILABLE_DETAIL} ({type(exc).__name__}: {exc})",
        ) from exc

    report_dir = Path(settings.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / f"{run_id}.pdf"
    try:
        produced = export_pdf(report, str(out_path))
    except Exception as exc:  # noqa: BLE001
        logger.exception("export_pdf failed for run %s", run_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report PDF export failed: {type(exc).__name__}: {exc}",
        ) from exc

    final_path = Path(produced) if produced else out_path
    if not final_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report PDF export did not produce a file",
        )
    return FileResponse(
        path=final_path,
        media_type="application/pdf",
        filename=f"report_{run_id}.pdf",
    )
