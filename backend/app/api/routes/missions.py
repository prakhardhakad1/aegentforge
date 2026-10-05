"""Mission routes: POST /api/missions, GET /api/missions, GET /api/missions/{id}."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.config import Settings, get_settings
from app.models import Dataset, Mission, User, new_uuid
from app.schemas.mission import MissionCreate, MissionListResponse, MissionRead
from app.templates_data import template_exists

logger = logging.getLogger("agentforge.missions")

router = APIRouter(
    prefix="/missions",
    tags=["Missions"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "",
    response_model=MissionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a mission",
    description=(
        "Describe a business goal in one sentence. Optionally bind a team "
        "template (``template_id``) and an uploaded dataset (``dataset_id``). "
        "Unknown template/dataset ids are rejected with 404."
    ),
)
def create_mission(
    payload: MissionCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MissionRead:
    del settings  # reserved for future per-key user binding
    if payload.template_id and not template_exists(db, payload.template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{payload.template_id}' not found",
        )
    if payload.dataset_id and db.get(Dataset, payload.dataset_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{payload.dataset_id}' not found — upload it first via POST /api/upload",
        )

    user = User(id=new_uuid(), display_name="guest")
    mission = Mission(
        id=new_uuid(),
        goal=payload.goal,
        template_id=payload.template_id,
        dataset_id=payload.dataset_id,
        user_id=user.id,
    )
    db.add_all([user, mission])
    db.commit()
    db.refresh(mission)
    logger.info(
        "Mission %s created (template=%s dataset=%s)",
        mission.id,
        mission.template_id,
        mission.dataset_id,
    )
    return MissionRead.model_validate(mission)


@router.get(
    "",
    response_model=MissionListResponse,
    summary="List missions",
    description="Paginated list, newest first. ``limit`` (1-200, default 50) and ``offset`` (>=0).",
)
def list_missions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> MissionListResponse:
    total = int(db.scalar(select(func.count(Mission.id))) or 0)
    rows = (
        db.execute(
            select(Mission)
            .order_by(Mission.created_at.desc(), Mission.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return MissionListResponse(
        missions=[MissionRead.model_validate(m) for m in rows], total=total
    )


@router.get(
    "/{mission_id}",
    response_model=MissionRead,
    summary="Get one mission",
    description="Fetch a single mission by id, or 404.",
)
def get_mission(mission_id: str, db: Session = Depends(get_db)) -> MissionRead:
    mission = db.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission '{mission_id}' not found",
        )
    return MissionRead.model_validate(mission)
