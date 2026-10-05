"""Run routes: POST /api/missions/{id}/runs, GET /api/runs/{id},
GET /api/runs/{id}/events and WS /api/runs/{id}/stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.api.deps import check_ws_auth, get_db, require_api_key
from app.config import Settings, get_settings
from app.models import Mission, Run, new_uuid
from app.schemas.common import EventsResponse
from app.schemas.run import RunCreate, RunRead, RunSnapshot
from app.services import runner
from app.services.snapshot import build_run_snapshot, events_after, get_history
from app.templates_data import template_exists

logger = logging.getLogger("agentforge.runs")

# Router-level dependencies would also run for the WebSocket route, where a
# Request-based dependency cannot be injected — so auth is applied per HTTP
# route here, and the WS route performs its own handshake check.
HTTP_AUTH = [Depends(require_api_key)]

router = APIRouter(tags=["Runs"])

WS_CLOSE_RUN_NOT_FOUND = 4404
WS_CLOSE_UNAUTHORIZED = 4401


@router.post(
    "/missions/{mission_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=HTTP_AUTH,
    summary="Start a run for a mission",
    description=(
        "Creates a Run row with status ``queued`` and schedules background "
        "execution (``RUN_MODE=demo`` simulated player or the live "
        "orchestrator engine). The response returns immediately; subscribe to "
        "WS /api/runs/{id}/stream or poll GET /api/runs/{id}/events for "
        "progress. An optional ``template_id`` overrides the mission's."
    ),
)
async def create_run(
    mission_id: str,
    payload: Optional[RunCreate] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RunRead:
    mission = db.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission '{mission_id}' not found",
        )
    template_id = (payload.template_id if payload else None) or mission.template_id
    if template_id and not template_exists(db, template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found",
        )

    run = Run(
        id=new_uuid(),
        mission_id=mission.id,
        status="queued",
        mode=settings.run_mode,
        template_id=template_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    task = asyncio.create_task(
        runner.execute_run_background(
            run_id=run.id,
            mission_id=mission.id,
            mission_text=mission.goal,
            template_id=run.template_id,
            dataset_id=mission.dataset_id,
            settings=settings,
        )
    )
    runner.register_task(run.id, task)
    logger.info("Run %s queued for mission %s (mode=%s)", run.id, mission.id, run.mode)
    return RunRead.model_validate(run)


@router.get(
    "/runs/{run_id}",
    response_model=RunSnapshot,
    dependencies=HTTP_AUTH,
    summary="Run snapshot",
    description=(
        "Assembles {run, mission, events, artifacts, token_usage, report?} for "
        "one run. Events come from the in-memory broadcaster (DB replay "
        "fallback); artifacts and token usage come from the database."
    ),
)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunSnapshot:
    del db  # existence is checked inside build_run_snapshot
    snapshot = build_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return RunSnapshot.model_validate(snapshot)


@router.get(
    "/runs/{run_id}/events",
    response_model=EventsResponse,
    dependencies=HTTP_AUTH,
    summary="Poll run events",
    description=(
        "Polling fallback for clients that cannot use WebSockets. Returns "
        "envelopes with ``seq > after_seq`` (default 0 = all)."
    ),
)
def get_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> EventsResponse:
    if db.get(Run, run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found",
        )
    return EventsResponse(events=events_after(run_id, after_seq))  # type: ignore[arg-type]


@router.websocket("/runs/{run_id}/stream")
async def stream_run_events(
    websocket: WebSocket,
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    """Live event stream for one run.

    On connect the server sends the full history first, then pushes every new
    event as it is published. Client messages (JSON):
      * ``{"type": "replay", "after_seq": N}`` — resend events with seq > N
      * ``{"type": "ping"}`` — server replies ``{"type": "pong", ...}``
      * anything else — server replies with a ``{"type": "error", ...}`` hint
    Unknown run -> accept + close(4404). Bad API key -> accept + close(4401).
    """
    if not check_ws_auth(websocket, settings):
        await websocket.accept()
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "run_id": run_id,
                    "payload": {"error": "unauthorized", "message": "Missing or invalid API key"},
                }
            )
        )
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return

    from app.db.base import session_scope

    with session_scope() as db:
        run_exists = db.get(Run, run_id) is not None
    if not run_exists:
        await websocket.accept()
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "run_id": run_id,
                    "payload": {"error": "not_found", "message": f"Run '{run_id}' not found"},
                }
            )
        )
        await websocket.close(code=WS_CLOSE_RUN_NOT_FOUND)
        return

    await websocket.accept()
    from realtime.broadcaster import get_broadcaster

    broadcaster = get_broadcaster()
    subscription = broadcaster.subscribe(run_id)
    last_sent_seq = 0

    async def _send_event(event: dict) -> bool:
        nonlocal last_sent_seq
        try:
            await websocket.send_text(json.dumps(event, default=str))
        except Exception:  # client went away
            return False
        seq = event.get("seq")
        if isinstance(seq, int) and seq > last_sent_seq:
            last_sent_seq = seq
        return True

    # Register the subscription BEFORE snapshotting history so nothing published
    # in between is lost; overlaps are removed via last_sent_seq dedupe.
    send_task: asyncio.Task = asyncio.create_task(subscription.__anext__())
    for _ in range(4):
        await asyncio.sleep(0)  # let the generator run to its first await point

    try:
        history = get_history(run_id)
        for event in history:
            if not await _send_event(event):
                return

        recv_task: asyncio.Task = asyncio.create_task(websocket.receive_text())
        while True:
            done, _pending = await asyncio.wait(
                {recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if send_task in done:
                try:
                    event = send_task.result()
                except StopAsyncIteration:
                    break
                if event.get("seq", 0) > last_sent_seq or not isinstance(
                    event.get("seq"), int
                ):
                    if not await _send_event(event):
                        break
                send_task = asyncio.create_task(subscription.__anext__())
            if recv_task in done:
                try:
                    raw = recv_task.result()
                except WebSocketDisconnect:
                    return
                await _handle_client_message(websocket, run_id, raw, _send_event)
                recv_task = asyncio.create_task(websocket.receive_text())
    except WebSocketDisconnect:
        return
    except Exception:  # pragma: no cover - defensive: never crash the loop
        logger.exception("WS stream crashed for run %s", run_id)
        return
    finally:
        for task in (locals().get("recv_task"), send_task):
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
        try:
            await subscription.aclose()
        except Exception:  # pragma: no cover - generator may already be closed
            pass


async def _handle_client_message(
    websocket: WebSocket,
    run_id: str,
    raw: str,
    send_event,
) -> None:
    """Handle one client control message (replay / ping / other)."""
    try:
        message = json.loads(raw)
        if not isinstance(message, dict):
            raise ValueError("message must be a JSON object")
    except (ValueError, TypeError):
        await send_event(
            {
                "type": "error",
                "run_id": run_id,
                "payload": {"error": "bad_message", "message": "Expected a JSON object"},
            }
        )
        return

    message_type = message.get("type")
    if message_type == "ping":
        from app.services.events import utc_now_iso

        await send_event({"type": "pong", "run_id": run_id, "ts": utc_now_iso()})
    elif message_type == "replay":
        after_seq = message.get("after_seq", 0)
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            await send_event(
                {
                    "type": "error",
                    "run_id": run_id,
                    "payload": {"error": "bad_replay", "message": "after_seq must be an integer >= 0"},
                }
            )
            return
        for event in events_after(run_id, after_seq):
            if not await send_event(event):
                return
    else:
        await send_event(
            {
                "type": "error",
                "run_id": run_id,
                "payload": {
                    "error": "unknown_type",
                    "message": "Supported client messages: {\"type\":\"replay\",\"after_seq\":N}, {\"type\":\"ping\"}",
                },
            }
        )
