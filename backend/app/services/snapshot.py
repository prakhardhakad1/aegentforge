"""Run snapshot assembly + event history access (broadcaster with DB fallback)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select

from app.db.base import session_scope
from app.models import AgentStep, Artifact, Mission, Run

logger = logging.getLogger("agentforge.snapshot")


def _broadcaster() -> Optional[Any]:
    """Return the broadcaster singleton, or None if unavailable."""
    try:
        from realtime.broadcaster import get_broadcaster

        return get_broadcaster()
    except Exception:  # pragma: no cover - broadcaster is stdlib-only
        logger.exception("Could not load realtime.broadcaster")
        return None


def _row_to_event(row: AgentStep) -> dict[str, Any]:
    return {
        "type": row.event_type,
        "run_id": row.run_id,
        "seq": row.seq,
        "ts": row.ts,
        "agent": row.agent,
        "payload": dict(row.payload_json or {}),
    }


def db_history(run_id: str) -> list[dict[str, Any]]:
    """All persisted events for a run, ordered by seq (DB replay source)."""
    with session_scope() as db:
        rows = (
            db.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run_id)
                .order_by(AgentStep.seq.asc())
            )
            .scalars()
            .all()
        )
    return [_row_to_event(row) for row in rows]


def db_events_after(run_id: str, after_seq: int) -> list[dict[str, Any]]:
    """Persisted events with seq > after_seq, ordered (polling fallback)."""
    with session_scope() as db:
        rows = (
            db.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run_id, AgentStep.seq > after_seq)
                .order_by(AgentStep.seq.asc())
            )
            .scalars()
            .all()
        )
    return [_row_to_event(row) for row in rows]


def get_history(run_id: str) -> list[dict[str, Any]]:
    """Full event history for a run: in-memory broadcaster first, DB fallback
    (covers process restarts, where the broadcaster is empty)."""
    broadcaster = _broadcaster()
    if broadcaster is not None:
        try:
            history = broadcaster.history(run_id)
            if history:
                return list(history)
        except Exception:
            logger.exception("Broadcaster history failed for run %s", run_id)
    return db_history(run_id)


def events_after(run_id: str, after_seq: int) -> list[dict[str, Any]]:
    """Events with seq > after_seq for polling clients (broadcaster first)."""
    broadcaster = _broadcaster()
    if broadcaster is not None:
        try:
            events = broadcaster.replay_after(run_id, after_seq)
            if events:
                return list(events)
        except Exception:
            logger.exception("Broadcaster replay failed for run %s", run_id)
    return db_events_after(run_id, after_seq)


def _run_dict(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "mission_id": run.mission_id,
        "status": run.status,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "mode": run.mode,
        "template_id": run.template_id,
        "error": run.error,
        "error_stage": run.error_stage,
    }


def _mission_dict(mission: Mission) -> dict[str, Any]:
    return {
        "id": mission.id,
        "goal": mission.goal,
        "template_id": mission.template_id,
        "dataset_id": mission.dataset_id,
        "created_at": mission.created_at,
    }


def _artifact_dict(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "subtask_id": artifact.subtask_id,
        "kind": artifact.kind,
        "name": artifact.name,
        "summary": artifact.summary,
        "path": artifact.path,
        "payload": dict(artifact.payload_json or {}),
        "created_at": artifact.created_at,
    }


def _default_usage() -> dict[str, Any]:
    return {
        "per_agent": {},
        "totals": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }


def build_run_snapshot(run_id: str) -> Optional[dict[str, Any]]:
    """Assemble the GET /api/runs/{id} RunSnapshot dict, or None if the run
    (or its mission) does not exist."""
    with session_scope() as db:
        run = db.get(Run, run_id)
        if run is None:
            return None
        mission = db.get(Mission, run.mission_id)
        if mission is None:
            logger.error("Run %s references missing mission %s", run_id, run.mission_id)
            return None
        artifacts = (
            db.execute(
                select(Artifact)
                .where(Artifact.run_id == run_id)
                .order_by(Artifact.created_at.asc(), Artifact.id.asc())
            )
            .scalars()
            .all()
        )
        artifact_dicts = [_artifact_dict(a) for a in artifacts]

    snapshot: dict[str, Any] = {
        "run": _run_dict(run),
        "mission": _mission_dict(mission),
        "events": get_history(run_id),
        "artifacts": artifact_dicts,
        "token_usage": run.token_usage_json or _default_usage(),
    }
    if run.report_json is not None:
        snapshot["report"] = run.report_json
    return snapshot
