"""Background run execution.

POST /api/missions/{id}/runs creates the Run row (status ``queued``) and
schedules :func:`execute_run_background` as an asyncio task on the server's
event loop. Two execution paths:

* ``RUN_MODE=demo`` — try Agent 7's ``realtime.simulate.SimulatedRunPlayer``;
  if it is not importable/drivable, fall back to the internal demo emitter in
  :mod:`app.services.demo_runner` (recorded in NOTES.md).
* ``RUN_MODE=live`` — call the pinned ``orchestrator.engine.execute_run``; if
  that import fails the run is marked **failed** with a clear ``run_failed``
  event. Success is never faked.

Every event (ours or foreign) flows through :class:`app.services.events.EventEmitter`,
which publishes to the broadcaster and persists to the DB.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from typing import Any, Coroutine, Optional

from app.db.base import session_scope
from app.models import Dataset, Run, Template, utcnow
from app.services.events import EventEmitter

logger = logging.getLogger("agentforge.runner")

# Strong references to scheduled tasks so the loop keeps them alive.
_tasks: dict[str, asyncio.Task] = {}


def register_task(run_id: str, task: asyncio.Task) -> None:
    """Keep a strong reference to a run's background task."""
    _tasks[run_id] = task


def unregister_task(run_id: str) -> None:
    """Drop the strong reference once the run finished."""
    _tasks.pop(run_id, None)


def get_task(run_id: str) -> Optional[asyncio.Task]:
    """Return the scheduled task for a run, if still tracked."""
    return _tasks.get(run_id)


class OrchestratorUnavailable(RuntimeError):
    """Raised when RUN_MODE=live but orchestrator.engine cannot be imported."""


async def execute_run_background(
    *,
    run_id: str,
    mission_id: str,
    mission_text: str,
    template_id: Optional[str],
    dataset_id: Optional[str],
    settings: Any,
) -> None:
    """Execute a run end-to-end: status transitions, events, artifacts,
    token usage, report and terminal state — never raising."""
    emitter = EventEmitter(run_id)
    emitter.seed_seq_from_db()
    template_dict = _load_template_dict(template_id)
    dataset_info = _load_dataset_info(dataset_id)
    try:
        _update_run(
            run_id,
            status="running",
        )
        if getattr(settings, "run_mode", "demo") == "live":
            await _execute_live(
                emitter,
                run_id=run_id,
                mission_text=mission_text,
                template_id=template_id,
                dataset_info=dataset_info,
            )
        else:
            await _execute_demo(
                emitter,
                run_id=run_id,
                mission_text=mission_text,
                template_dict=template_dict,
                dataset_info=dataset_info,
                settings=settings,
            )
    except OrchestratorUnavailable as exc:
        logger.error("Run %s failed: %s", run_id, exc)
        await _finalize_failed(emitter, run_id=run_id, error=str(exc), stage="startup")
    except Exception as exc:  # noqa: BLE001 - the runner must never crash the app
        logger.exception("Run %s crashed unexpectedly", run_id)
        await _finalize_failed(
            emitter, run_id=run_id, error=f"{type(exc).__name__}: {exc}", stage="execution"
        )
    finally:
        unregister_task(run_id)


# ── demo path ───────────────────────────────────────────────────────────


async def _execute_demo(
    emitter: EventEmitter,
    *,
    run_id: str,
    mission_text: str,
    template_dict: Optional[dict[str, Any]],
    dataset_info: Optional[dict[str, Any]],
    settings: Any,
) -> None:
    player_coro = _try_simulated_player(
        mission_text=mission_text,
        template_dict=template_dict,
        dataset_info=dataset_info,
        emitter=emitter,
    )
    if player_coro is not None:
        logger.info("Run %s: driving realtime.simulate.SimulatedRunPlayer", run_id)
        try:
            await player_coro
            await emitter.drain()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"SimulatedRunPlayer raised {type(exc).__name__}: {exc}"
            ) from exc
        terminal = {"run_finished", "run_failed"}
        if terminal & emitter.seen_types:
            # The player owns the whole event flow, including its terminal
            # event; finalize with what streamed through the emitter. The
            # structured report is built from the finished run so demo runs
            # serve the same deliverable as live runs.
            await _finalize_success(
                run_id,
                emitter=emitter,
                token_usage=emitter.accumulated_usage(),
                report=_report_for_finished_run(
                    run_id=run_id,
                    mission_text=mission_text,
                    template_dict=template_dict,
                    token_usage=emitter.accumulated_usage(),
                    emitter=emitter,
                ),
                emit_run_finished="run_finished" not in emitter.seen_types,
            )
            return
        raise RuntimeError(
            "SimulatedRunPlayer completed without emitting run_finished/run_failed"
        )

    # Fallback: internal demo emitter (Agent 7's player not landed yet).
    from app.services.demo_runner import run_demo_mission

    logger.info("Run %s: using internal demo emitter fallback", run_id)
    result = await run_demo_mission(
        run_id=run_id,
        mission=mission_text,
        emitter=emitter,
        template=template_dict,
        dataset_info=dataset_info,
        settings=settings,
    )
    await _finalize_success(
        run_id,
        emitter=emitter,
        token_usage=emitter.accumulated_usage(),
        report=result.get("report"),
        emit_run_finished=True,
    )


def _report_for_finished_run(
    *,
    run_id: str,
    mission_text: str,
    template_dict: Optional[dict[str, Any]],
    token_usage: dict[str, Any],
    emitter: EventEmitter,
) -> Optional[dict[str, Any]]:
    """Build the structured report for a finished (demo) run via the
    orchestrator's insight engine. Returns None (logged) when the module is
    unavailable or building fails — never fakes a report."""
    try:
        from orchestrator.report import build_report
    except Exception:  # noqa: BLE001 - report engine not installed yet
        logger.info("Run %s: orchestrator.report unavailable; no report built", run_id)
        return None
    try:
        from app.services.snapshot import build_run_snapshot

        snapshot = build_run_snapshot(run_id) or {}
        run_dict = snapshot.get("run") or {}
        plan = emitter.plan
        if plan is None:
            for event in snapshot.get("events", []):
                if event.get("type") == "plan_created":
                    plan = event.get("payload", {}).get("subtasks")
                    break
        run_result = {
            "run_id": run_id,
            "mission": mission_text,
            "status": run_dict.get("status", "succeeded"),
            "plan": plan or [],
            "steps": snapshot.get("events", []),
            "artifacts": snapshot.get("artifacts", []),
            "token_usage": token_usage,
            "errors": [],
        }
        style = (template_dict or {}).get("id") or "default"
        return build_report(run_result, style=style)
    except Exception:  # noqa: BLE001 - a broken report build must not fail the run
        logger.exception("Run %s: report build failed; continuing without report", run_id)
        return None


def _try_simulated_player(
    *,
    mission_text: str,
    template_dict: Optional[dict[str, Any]],
    dataset_info: Optional[dict[str, Any]],
    emitter: EventEmitter,
) -> Optional[Coroutine[Any, Any, None]]:
    """Build a coroutine driving Agent 7's SimulatedRunPlayer, adapting to its
    constructor/method signature as best we can. Returns None when the player
    is unavailable or incompatible (then the internal demo emitter is used)."""
    try:
        from realtime.simulate import SimulatedRunPlayer
    except Exception:
        return None

    sink = emitter.sync_sink()
    # Demo pacing: DEMO_RUN_SPEED divides the player's scripted delays
    # (1.0 = watchable ~33 s demo; higher = faster; <=0 = no delays).
    raw_speed = os.getenv("DEMO_RUN_SPEED", "1.0")
    try:
        demo_speed = float(raw_speed)
    except ValueError:
        logger.warning("DEMO_RUN_SPEED=%r is not a number; using 1.0", raw_speed)
        demo_speed = 1.0
    candidate_kwargs: dict[str, Any] = {
        "run_id": emitter.run_id,
        "mission": mission_text,
        "mission_text": mission_text,
        "goal": mission_text,
        "template": template_dict,
        "template_id": (template_dict or {}).get("id"),
        "dataset_path": (dataset_info or {}).get("path"),
        "dataset_columns": (dataset_info or {}).get("columns"),
        "dataset_info": dataset_info,
        "on_event": sink,
        "speed": demo_speed,
    }
    try:
        params = {
            name
            for name, p in inspect.signature(SimulatedRunPlayer.__init__).parameters.items()
            if name != "self"
            and p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        kwargs = {k: v for k, v in candidate_kwargs.items() if k in params}
        player = SimulatedRunPlayer(**kwargs)
    except TypeError:
        logger.warning(
            "SimulatedRunPlayer constructor incompatible with known kwargs; "
            "falling back to internal demo emitter"
        )
        return None
    except Exception:  # noqa: BLE001 - any player construction failure is non-fatal
        logger.exception("SimulatedRunPlayer construction failed; using fallback")
        return None

    for method_name in ("play", "run", "execute", "start"):
        method = getattr(player, method_name, None)
        if not callable(method):
            continue
        try:
            sig = inspect.signature(method)
            accepts_event = "on_event" in sig.parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins
            accepts_event = False
        try:
            coro = method(on_event=sink) if accepts_event else method()
        except TypeError:
            try:
                coro = method()
            except TypeError:
                continue
        if inspect.iscoroutine(coro) or inspect.isawaitable(coro):
            return coro
    logger.warning(
        "SimulatedRunPlayer exposes no awaitable play/run/execute/start; "
        "falling back to internal demo emitter"
    )
    return None


# ── live path ───────────────────────────────────────────────────────────


async def _execute_live(
    emitter: EventEmitter,
    *,
    run_id: str,
    mission_text: str,
    template_id: Optional[str],
    dataset_info: Optional[dict[str, Any]],
) -> None:
    try:
        from orchestrator.engine import execute_run
    except Exception as exc:  # ImportError or a broken half-landed module
        raise OrchestratorUnavailable(
            "orchestrator.engine is not importable "
            f"({type(exc).__name__}: {exc}). Live runs need the orchestrator "
            "package (Agent 3) installed; refusing to fake a successful run."
        ) from exc

    columns = (dataset_info or {}).get("columns")
    result = await execute_run(
        mission=mission_text,
        template_id=template_id,
        dataset_path=(dataset_info or {}).get("path"),
        dataset_columns=list(columns) if columns else None,
        on_event=emitter.sync_sink(),
    )
    await emitter.drain()

    data: dict[str, Any]
    if hasattr(result, "to_dict"):
        data = dict(result.to_dict())
    elif isinstance(result, dict):
        data = dict(result)
    else:  # pragma: no cover - defensive
        data = {}

    status = data.get("status") or ("run_failed" in emitter.seen_types and "failed") or "succeeded"
    if status not in ("succeeded", "failed", "partial"):
        status = "partial"
    token_usage = data.get("token_usage") or emitter.accumulated_usage()
    report = data.get("report")
    errors = data.get("errors") or []

    if status == "failed":
        await _finalize_failed(
            emitter,
            run_id=run_id,
            error="; ".join(str(e) for e in errors) or "orchestrator reported failure",
            stage="orchestrator",
            emit_run_failed="run_failed" not in emitter.seen_types,
        )
    else:
        await _finalize_success(
            run_id,
            emitter=emitter,
            token_usage=token_usage,
            report=report,
            status=status,
            errors=errors,
            emit_run_finished="run_finished" not in emitter.seen_types,
        )


# ── DB finalization helpers ─────────────────────────────────────────────


def _load_template_dict(template_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not template_id:
        return None
    try:
        with session_scope() as db:
            row = db.get(Template, template_id)
            if row is not None:
                return {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "tags": list(row.tags_json or []),
                    "team": list(row.team_json or []),
                    "planner_prompt": row.planner_prompt,
                    "sample_mission": row.sample_mission,
                    "expected_dag": list(row.expected_dag_json or []),
                    "report_outline": list(row.report_outline_json or []),
                }
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not load template %s", template_id)
    from app.templates_data import get_template_spec

    return get_template_spec(template_id)


def _load_dataset_info(dataset_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not dataset_id:
        return None
    try:
        with session_scope() as db:
            row = db.get(Dataset, dataset_id)
            if row is not None:
                return {
                    "id": row.id,
                    "filename": row.filename,
                    "path": row.path,
                    "row_count": row.row_count,
                    "columns": list(row.columns_json or []),
                    "dtypes": dict(row.dtypes_json or {}),
                }
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not load dataset %s", dataset_id)
    return None


def _update_run(run_id: str, **fields: Any) -> None:
    """Update columns on the run row (short-lived session)."""
    with session_scope() as db:
        run = db.get(Run, run_id)
        if run is None:
            logger.error("Run row %s vanished before update", run_id)
            return
        for key, value in fields.items():
            setattr(run, key, value)
        db.commit()


async def _finalize_success(
    run_id: str,
    *,
    emitter: EventEmitter,
    token_usage: dict[str, Any],
    report: Optional[dict[str, Any]],
    status: str = "succeeded",
    errors: Optional[list[Any]] = None,
    emit_run_finished: bool = True,
) -> None:
    """Persist final run state, then emit the terminal event."""
    fields: dict[str, Any] = {
        "status": status,
        "finished_at": utcnow(),
        "token_usage_json": token_usage,
    }
    if report is not None:
        fields["report_json"] = report
    if emitter.plan is not None:
        fields["plan_json"] = emitter.plan
    if errors:
        fields["error"] = "; ".join(str(e) for e in errors)
    _update_run(run_id, **fields)
    if emit_run_finished:
        await emitter.emit(
            "run_finished", agent=None, payload={"report_ready": report is not None}
        )


async def _finalize_failed(
    emitter: EventEmitter,
    *,
    run_id: str,
    error: str,
    stage: str,
    emit_run_failed: bool = True,
) -> None:
    """Mark the run failed, persist the error, emit run_failed."""
    _update_run(
        run_id,
        status="failed",
        finished_at=utcnow(),
        error=error,
        error_stage=stage,
    )
    if emit_run_failed:
        await emitter.emit(
            "run_failed",
            agent=None,
            payload={"error": error, "stage": stage},
        )
