"""Template marketplace route: GET /api/templates."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.models import Template
from app.schemas.template import (
    TemplateListResponse,
    TemplateRead,
    template_row_to_dict,
)

logger = logging.getLogger("agentforge.templates")

router = APIRouter(
    prefix="/templates",
    tags=["Templates"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "",
    response_model=TemplateListResponse,
    summary="List team templates",
    description=(
        "Returns the prebuilt agent-team templates (market_research_team, "
        "sales_insights_team, support_triage_team), seeded into the database "
        "at startup from app.templates_data."
    ),
)
def list_templates(db: Session = Depends(get_db)) -> TemplateListResponse:
    rows = db.execute(select(Template).order_by(Template.id.asc())).scalars().all()
    templates = [TemplateRead.model_validate(template_row_to_dict(row)) for row in rows]
    if not rows:
        # Defensive: lifespan seeding may have been skipped (e.g. custom test
        # setup). Fall back to the in-code specs so the marketplace is never
        # silently empty.
        from app.schemas.template import template_dict_to_read
        from app.templates_data import TEMPLATES

        templates = [template_dict_to_read(spec) for spec in TEMPLATES]
    return TemplateListResponse(templates=templates)
