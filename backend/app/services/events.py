"""Event plumbing: pinned envelope construction, broadcaster publishing, and
DB persistence of every event (AgentStep rows) plus Artifact rows.

The broadcaster import is deferred to call time so tests (and Agent 7's final
implementation) can replace the module freely. Because INTERFACES.md shows
``async publish(event: dict)`` while the coordinator stub uses
``publish(run_id, event)``, :func:`publish_event` adapts to whichever signature
the installed broadcaster exposes (see NOTES.md).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

from sqlalchemy import select

from app.db.base import get_session_factory
from app.models import AgentStep, Artifact
from app.schemas.common import EVENT_TYPES

logger = logging.getLogger("agentforge.events")


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp with a ``Z`` suffix (pinned envelope format)."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _publish_arity(broadcaster: Any) -> int:
    """Detect whether ``broadcaster.publish`` takes (run_id, event) or (event)."""
    cached = getattr(broadcaster, "_agentforge_publish_arity", None)
    if cached in (1, 2):
        return int(cached)
    arity = 2  # coordinator stub signature
    try:
        params = [
            p
            for p in inspect.signature(broadcaster.publish).parameters.values()
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if params and params[0].name in ("self",):
            params = params[1:]
        arity = 2 if len(params) >= 2 else 1
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        pass
    try:
        broadcaster._agentforge_publish_arity = arity
    except Exception:  # pragma: no cover - read-only objects
        pass
    return arity


async def publish_event(broadcaster: Any, run_id: str, event: dict) -> dict:
    """Publish an event through whichever broadcaster signature is installed.

    Returns the (possibly seq-stamped) event as reported by the broadcaster —
    that returned dict is the canonical copy that gets persisted.
    """
    if _publish_arity(broadcaster) >= 2:
        stamped = await broadcaster.publish(run_id, event)
    else:
        stamped = await broadcaster.publish(event)
    if not isinstance(stamped, dict):
        return event
    return stamped


class EventEmitter:
    """Creates pinned envelopes for one run, publishes them to the broadcaster
    and persists them to the database.

    Also acts as the sink for foreign ``on_event`` callbacks (the orchestrator
    engine and Agent 7's SimulatedRunPlayer): pass :meth:`sync_sink` and every
    received event is normalized, published and persisted.
    """

    def __init__(
        self,
        run_id: str,
        session_factory: Optional[Any] = None,
        broadcaster: Optional[Any] = None,
    ) -> None:
        self.run_id = run_id
        self.session_factory = session_factory or get_session_factory()
        self.broadcaster = broadcaster
        self._seq = 0
        self._seen_types: set[str] = set()
        self._plan: Optional[list[dict[str, Any]]] = None
        self._usage: dict[str, Any] = {
            "per_agent": {},
            "totals": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        }
        self._pending: set[asyncio.Task] = set()
        self._warned_unknown_types: set[str] = set()

    # ── sequencing ──────────────────────────────────────────────────────

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def observe_seq(self, seq: int) -> None:
        """Track a foreign seq so our counter never collides or regresses."""
        if seq > self._seq:
            self._seq = seq

    def seed_seq_from_db(self) -> None:
        """Start counting after any events already persisted for this run
        (defends against re-driving a run after a restart)."""
        try:
            with self.session_factory() as db:
                row = db.execute(
                    select(AgentStep.seq)
                    .where(AgentStep.run_id == self.run_id)
                    .order_by(AgentStep.seq.desc())
                    .limit(1)
                ).scalar()
            self._seq = int(row or 0)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Could not seed seq from DB for run %s", self.run_id)
            self._seq = 0

    # ── emission ────────────────────────────────────────────────────────

    def build_event(
        self,
        event_type: str,
        agent: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Construct a pinned envelope with the next seq for this run."""
        return {
            "type": event_type,
            "run_id": self.run_id,
            "seq": self.next_seq(),
            "ts": utc_now_iso(),
            "agent": agent,
            "payload": dict(payload or {}),
        }

    async def emit(
        self,
        event_type: str,
        agent: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build + publish + persist one event of our own making."""
        event = self.build_event(event_type, agent, payload)
        return await self.process_event(event)

    async def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalize, publish and persist an event (ours or foreign)."""
        ev = self.normalize_event(event)
        self._observe(ev)
        if self.broadcaster is None:
            try:
                from realtime.broadcaster import get_broadcaster

                self.broadcaster = get_broadcaster()
            except Exception:  # pragma: no cover - broadcaster is stdlib-only
                logger.exception("Could not import realtime.broadcaster")
                self.broadcaster = None
        if self.broadcaster is not None:
            try:
                ev = await publish_event(self.broadcaster, self.run_id, ev)
            except Exception:
                # Broadcasting must never kill a run; DB still gets the event.
                logger.exception(
                    "Failed to publish event %s for run %s", ev.get("type"), self.run_id
                )
        self.persist(ev)
        return ev

    def normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Force an incoming event (possibly from a foreign agent) into the
        pinned envelope shape, assigning seq when missing/invalid."""
        if not isinstance(event, dict):
            event = {"type": "unknown", "payload": {"raw": repr(event)}}
        ev = dict(event)
        ev["run_id"] = self.run_id
        event_type = ev.get("type")
        if not isinstance(event_type, str) or not event_type:
            ev["type"] = "unknown"
            event_type = "unknown"
        seq = ev.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            ev["seq"] = self.next_seq()
        else:
            self.observe_seq(seq)
        payload_value = ev.get("payload")
        if payload_value is None:
            ev["payload"] = {}
        elif not isinstance(payload_value, dict):
            ev["payload"] = {"value": payload_value}
        if not isinstance(ev.get("agent"), str):
            ev["agent"] = None
        ev.setdefault("ts", utc_now_iso())
        if event_type not in EVENT_TYPES and event_type not in self._warned_unknown_types:
            self._warned_unknown_types.add(event_type)
            logger.warning(
                "Run %s produced non-pinned event type %r", self.run_id, event_type
            )
        return ev

    def _observe(self, ev: dict[str, Any]) -> None:
        """Track terminal events, the plan and token usage as events flow by."""
        event_type = ev.get("type", "")
        self._seen_types.add(event_type)
        if event_type == "plan_created":
            subtasks = ev.get("payload", {}).get("subtasks")
            if isinstance(subtasks, list):
                self._plan = subtasks
        elif event_type == "token_update":
            payload = ev.get("payload", {})
            self._accumulate_usage(payload)

    def _accumulate_usage(self, payload: dict[str, Any]) -> None:
        agent = payload.get("agent") or "unknown"
        try:
            input_tokens = int(payload.get("input_tokens") or 0)
        except (TypeError, ValueError):
            input_tokens = 0
        try:
            output_tokens = int(payload.get("output_tokens") or 0)
        except (TypeError, ValueError):
            output_tokens = 0
        try:
            cost = float(payload.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        per_agent = self._usage["per_agent"].setdefault(
            agent, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        per_agent["input_tokens"] += input_tokens
        per_agent["output_tokens"] += output_tokens
        per_agent["cost_usd"] = round(per_agent["cost_usd"] + cost, 6)
        totals = self._usage["totals"]
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        totals["cost_usd"] = round(totals["cost_usd"] + cost, 6)

    # ── persistence ─────────────────────────────────────────────────────

    def persist(self, ev: dict[str, Any]) -> None:
        """Write the event to ``agent_steps`` (and ``artifacts`` for
        artifact_created). Failures are logged, never raised — the run must
        keep flowing."""
        try:
            payload = ev.get("payload") or {}
            with self.session_factory() as db:
                db.add(
                    AgentStep(
                        run_id=self.run_id,
                        seq=int(ev.get("seq") or 0),
                        event_type=str(ev.get("type") or "unknown"),
                        agent=ev.get("agent"),
                        subtask_id=payload.get("subtask_id"),
                        payload_json=payload,
                        ts=ev.get("ts"),
                    )
                )
                if ev.get("type") == "artifact_created":
                    self._upsert_artifact(db, payload)
                db.commit()
        except Exception:
            logger.exception(
                "Failed to persist event seq=%s for run %s",
                ev.get("seq"),
                self.run_id,
            )

    def _upsert_artifact(self, db: Any, payload: dict[str, Any]) -> None:
        artifact_id = payload.get("artifact_id") or f"artifact_{self.next_seq()}"
        row = db.get(Artifact, artifact_id)
        if row is None:
            row = Artifact(
                id=str(artifact_id),
                run_id=self.run_id,
                subtask_id=payload.get("subtask_id"),
                kind=str(payload.get("kind") or "file"),
                name=payload.get("name"),
                summary=payload.get("summary"),
                path=payload.get("path"),
                payload_json=payload,
            )
            db.add(row)
        else:
            row.kind = str(payload.get("kind") or row.kind)
            row.name = payload.get("name") or row.name
            row.summary = payload.get("summary") or row.summary
            row.path = payload.get("path") or row.path
            row.payload_json = payload

    # ── sinks for foreign producers ─────────────────────────────────────

    def sync_sink(self) -> Callable[[dict], None]:
        """Synchronous ``on_event`` callback for engines/players running on the
        same event loop: schedules processing and tracks the tasks so
        :meth:`drain` can await them."""
        loop = asyncio.get_running_loop()

        def _sink(event: dict) -> None:
            task = loop.create_task(self.process_event(event))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

        return _sink

    async def drain(self) -> None:
        """Await every sink task spawned so far (ensures all events are
        published + persisted before the run is finalized)."""
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    # ── introspection for the runner ────────────────────────────────────

    @property
    def seen_types(self) -> set[str]:
        return set(self._seen_types)

    @property
    def plan(self) -> Optional[list[dict[str, Any]]]:
        return self._plan

    def accumulated_usage(self) -> dict[str, Any]:
        """Canonical token_usage dict assembled from token_update events."""
        import copy

        return copy.deepcopy(self._usage)
