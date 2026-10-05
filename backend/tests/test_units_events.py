"""Unit tests for the event emitter building blocks."""

from __future__ import annotations

import pytest

from app.db.base import init_db
from app.services.events import (
    EventEmitter,
    _publish_arity,
    utc_now_iso,
)


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    init_db()  # these unit tests may run before any lifespan-backed test


class TwoArgBroadcaster:
    """Mimics the coordinator stub signature: publish(run_id, event)."""

    async def publish(self, run_id: str, event: dict) -> dict:
        return dict(event, seq=event.get("seq", 1))


class OneArgBroadcaster:
    """Mimics the INTERFACES.md signature: async publish(event: dict)."""

    async def publish(self, event: dict) -> dict:
        return dict(event)


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, run_id: str, event: dict) -> dict:
        self.published.append(event)
        return event


@pytest.mark.asyncio
async def test_publish_arity_detection() -> None:
    assert _publish_arity(TwoArgBroadcaster()) == 2
    assert _publish_arity(OneArgBroadcaster()) == 1


@pytest.mark.asyncio
async def test_event_emitter_envelope_and_persistence() -> None:
    from app.db.base import get_session_factory
    from app.models import AgentStep, Artifact, Run, Mission, new_uuid

    run_id = new_uuid()
    with get_session_factory()() as db:
        mission = Mission(id=new_uuid(), goal="unit mission")
        db.add(mission)
        db.add(Run(id=run_id, mission_id=mission.id, status="running"))
        db.commit()

    emitter = EventEmitter(run_id)
    broadcaster = RecordingBroadcaster()
    emitter.broadcaster = broadcaster

    event = await emitter.emit(
        "agent_started", agent="analyst", payload={"subtask_id": "st3", "title": "T"}
    )
    assert event["type"] == "agent_started"
    assert event["run_id"] == run_id
    assert event["seq"] == 1
    assert event["ts"] == utc_now_iso()
    assert broadcaster.published == [event]

    artifact_payload = {
        "subtask_id": "st3",
        "artifact_id": "art_unit_1",
        "kind": "table",
        "name": "summary",
        "summary": "s",
    }
    await emitter.emit("artifact_created", agent="analyst", payload=artifact_payload)

    with get_session_factory()() as db:
        steps = db.query(AgentStep).filter(AgentStep.run_id == run_id).all()
        assert len(steps) == 2
        assert [s.seq for s in steps] == [1, 2]
        assert steps[1].event_type == "artifact_created"
        artifact = db.get(Artifact, "art_unit_1")
        assert artifact is not None
        assert artifact.kind == "table"
        assert artifact.run_id == run_id


@pytest.mark.asyncio
async def test_emiter_normalizes_foreign_events() -> None:
    emitter = EventEmitter("run-unit")
    emitter.broadcaster = RecordingBroadcaster()

    # missing seq/ts/agent/payload -> coerced to the pinned envelope
    normalized = await emitter.process_event({"type": "thought_summary"})
    assert normalized["seq"] == 1
    assert normalized["agent"] is None
    assert normalized["payload"] == {}
    assert normalized["ts"].endswith("Z")

    # foreign seq respected, counter advances past it
    foreign = await emitter.process_event(
        {"type": "token_update", "seq": 10, "payload": {"agent": "critic",
         "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01}}
    )
    assert foreign["seq"] == 10
    mine = await emitter.emit("step_completed")
    assert mine["seq"] == 11

    usage = emitter.accumulated_usage()
    assert usage["per_agent"]["critic"]["input_tokens"] == 100
    assert usage["totals"]["cost_usd"] == pytest.approx(0.01)

    # unknown event types are tolerated and logged, not raised
    weird = await emitter.process_event({"type": "mystery", "payload": "not-a-dict"})
    assert weird["payload"]["value"] == "not-a-dict"
    assert "mystery" in emitter.seen_types


@pytest.mark.asyncio
async def test_emitter_survives_broadcaster_failure() -> None:
    class ExplodingBroadcaster:
        async def publish(self, run_id: str, event: dict) -> dict:
            raise RuntimeError("bus down")

    emitter = EventEmitter("run-boom")
    emitter.broadcaster = ExplodingBroadcaster()
    event = await emitter.emit("run_started")  # must not raise
    assert event["type"] == "run_started"


def test_sync_sink_defers_until_drained() -> None:
    import asyncio

    from app.db.base import get_session_factory
    from app.models import Mission, Run, new_uuid

    async def scenario() -> None:
        run_id = new_uuid()
        with get_session_factory()() as db:
            mission = Mission(id=new_uuid(), goal="sink mission")
            db.add(mission)
            db.add(Run(id=run_id, mission_id=mission.id, status="running"))
            db.commit()

        emitter = EventEmitter(run_id)
        emitter.broadcaster = RecordingBroadcaster()
        sink = emitter.sync_sink()
        sink({"type": "run_started"})
        sink({"type": "run_finished", "payload": {"report_ready": True}})
        await emitter.drain()
        assert emitter.seen_types >= {"run_started", "run_finished"}
        assert emitter.plan is None

        # plan tracking
        sink({"type": "plan_created", "payload": {"subtasks": [{"id": "s1"}]}})
        await emitter.drain()
        assert emitter.plan == [{"id": "s1"}]

    asyncio.run(scenario())
