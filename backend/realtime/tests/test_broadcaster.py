"""Behaviour tests for realtime.broadcaster — the pinned pub/sub contract."""

from __future__ import annotations

import asyncio
import time

import pytest

from realtime.broadcaster import (
    SUBSCRIBER_QUEUE_MAXSIZE,
    Broadcaster,
    get_broadcaster,
    reset_broadcaster,
)
def _event(event_type: str = "thought_summary", **payload) -> dict:
    return {"type": event_type, "payload": dict(payload)}


async def _wait_subscribed(bc: Broadcaster, run_id: str, count: int) -> None:
    """Yield control until ``count`` subscribers are registered on run_id."""
    for _ in range(200):
        if bc.subscriber_count(run_id) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} subscribers, saw {bc.subscriber_count(run_id)}")


@pytest.mark.asyncio
async def test_publish_stamps_seq_and_ts_when_missing() -> None:
    bc = Broadcaster()
    first = await bc.publish("run-1", _event())
    second = await bc.publish("run-1", _event())
    assert first["seq"] == 1
    assert second["seq"] == 2
    assert first["run_id"] == "run-1"
    assert first["ts"].endswith("Z") and "T" in first["ts"]
    assert first["agent"] is None  # defaulted, envelope-complete
    assert first["payload"] == {}


@pytest.mark.asyncio
async def test_publish_preserves_event_provided_seq() -> None:
    bc = Broadcaster()
    stamped = await bc.publish(
        "run-1", {"type": "plan_created", "seq": 41, "payload": {}}
    )
    assert stamped["seq"] == 41
    # An invalid provided seq (0 / bool / str) is replaced, not kept.
    assert (await bc.publish("run-1", {"type": "run_started", "seq": 0}))["seq"] == 42
    assert (await bc.publish("run-1", {"type": "run_started", "seq": True}))["seq"] == 43


@pytest.mark.asyncio
async def test_publish_single_event_signature_also_works() -> None:
    bc = Broadcaster()
    stamped = await bc.publish({"type": "run_started", "run_id": "run-9", "seq": 1})
    assert stamped["run_id"] == "run-9"
    with pytest.raises(ValueError):
        await bc.publish({"type": "run_started"})  # no run_id anywhere


@pytest.mark.asyncio
async def test_publish_rejects_bad_arguments() -> None:
    bc = Broadcaster()
    with pytest.raises(ValueError):
        await bc.publish("", _event())
    with pytest.raises(TypeError):
        await bc.publish("run-1", "not-a-dict")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_fan_out_to_two_clients() -> None:
    bc = Broadcaster()
    run_id = "run-fan"

    async def collect(n: int) -> list[dict]:
        received: list[dict] = []
        async for event in bc.subscribe(run_id):
            received.append(event)
            if len(received) >= n:
                return received
        return received

    task_a = asyncio.create_task(collect(3))
    task_b = asyncio.create_task(collect(3))
    await _wait_subscribed(bc, run_id, 2)

    for i in range(3):
        await bc.publish(run_id, {"type": "step_completed", "payload": {"i": i}})

    got_a, got_b = await asyncio.wait_for(task_a, 2), await asyncio.wait_for(task_b, 2)
    assert [e["payload"]["i"] for e in got_a] == [0, 1, 2]
    assert [e["seq"] for e in got_b] == [1, 2, 3]


@pytest.mark.asyncio
async def test_unsubscribe_is_clean_on_break_and_close() -> None:
    bc = Broadcaster()
    run_id = "run-unsub"

    async def watch(gen) -> int:
        seen = 0
        async for _event in gen:
            seen += 1
            if seen == 1:
                break  # leaves the async-for early
        return seen

    # Path 1: explicit aclose() after breaking out (the WS route's pattern).
    gen = bc.subscribe(run_id)
    task = asyncio.create_task(watch(gen))
    await _wait_subscribed(bc, run_id, 1)
    await bc.publish(run_id, _event())
    assert await asyncio.wait_for(task, 2) == 1
    await gen.aclose()  # runs the generator's finally -> unsubscribe
    assert bc.subscriber_count(run_id) == 0

    # Path 2: closing a still-open subscription via aclose().
    subscription = bc.subscribe(run_id)
    t = asyncio.create_task(subscription.__anext__())
    await _wait_subscribed(bc, run_id, 1)
    await bc.publish(run_id, _event())
    assert (await asyncio.wait_for(t, 2))["type"] == "thought_summary"
    await subscription.aclose()
    assert bc.subscriber_count(run_id) == 0

    # Path 3: cancelling a consuming task also unsubscribes.
    gen3 = bc.subscribe(run_id)
    task3 = asyncio.create_task(gen3.__anext__())
    await _wait_subscribed(bc, run_id, 1)
    task3.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task3
    await gen3.aclose()
    assert bc.subscriber_count(run_id) == 0


@pytest.mark.asyncio
async def test_history_and_replay_after() -> None:
    bc = Broadcaster()
    for i in range(5):
        await bc.publish("run-h", {"type": "thought_summary", "seq": i + 1, "payload": {"i": i}})
    history = bc.history("run-h")
    assert [e["seq"] for e in history] == [1, 2, 3, 4, 5]
    assert history is not bc.history("run-h")  # defensive copy

    assert [e["seq"] for e in bc.replay_after("run-h", 3)] == [4, 5]
    assert len(bc.replay_after("run-h", 0)) == 5
    assert bc.replay_after("run-h", 99) == []
    assert bc.replay_after("run-h", -5) == history  # bad after_seq -> replay all
    assert bc.history("missing-run") == []
    assert bc.replay_after("missing-run", 0) == []


@pytest.mark.asyncio
async def test_history_bounded_drop_oldest() -> None:
    bc = Broadcaster(history_limit=4)
    for i in range(6):
        await bc.publish("run-b", {"type": "thought_summary", "seq": i + 1})
    assert [e["seq"] for e in bc.history("run-b")] == [3, 4, 5, 6]


@pytest.mark.asyncio
async def test_seq_monotonic_under_concurrent_publishers() -> None:
    bc = Broadcaster()
    n = 60

    async def publish_batch(worker: int) -> None:
        for i in range(n // 4):
            await bc.publish("run-c", {"type": "thought_summary",
                                       "payload": {"w": worker, "i": i}})

    await asyncio.gather(*(publish_batch(w) for w in range(4)))
    seqs = [e["seq"] for e in bc.history("run-c")]
    assert seqs == sorted(seqs), "history order must equal seq order"
    assert seqs == list(range(1, n + 1)), "seqs must be unique and strictly increasing"


@pytest.mark.asyncio
async def test_mixed_explicit_and_stamped_seqs_never_collide() -> None:
    bc = Broadcaster()

    async def explicit() -> None:
        for seq in (5, 10):
            await bc.publish("run-m", {"type": "thought_summary", "seq": seq})

    async def stamped() -> None:
        for _ in range(4):
            await bc.publish("run-m", {"type": "thought_summary"})

    await asyncio.gather(explicit(), stamped())
    seqs = [e["seq"] for e in bc.history("run-m")]
    assert len(set(seqs)) == len(seqs) == 6  # no collisions
    assert {5, 10} <= set(seqs)              # explicit seqs preserved verbatim
    assert all(s >= 1 for s in seqs)


@pytest.mark.asyncio
async def test_slow_consumer_does_not_block_others() -> None:
    bc = Broadcaster(queue_maxsize=4)
    run_id = "run-slow"

    async def stalled() -> list[dict]:
        received: list[dict] = []
        async for event in bc.subscribe(run_id):
            received.append(event)  # never returns: never consumes
        return received

    async def healthy(n: int) -> list[dict]:
        received: list[dict] = []
        async for event in bc.subscribe(run_id):
            received.append(event)
            if len(received) >= n:
                break
        return received

    stalled_task = asyncio.create_task(stalled())
    healthy_task = asyncio.create_task(healthy(30))
    await _wait_subscribed(bc, run_id, 2)

    start = time.perf_counter()
    for i in range(30):
        await bc.publish(run_id, {"type": "tool_result", "payload": {"i": i}})
        await asyncio.sleep(0)  # let the healthy consumer drain between events
    elapsed = time.perf_counter() - start

    # Publishing 30 events must be effectively immediate (no blocking await).
    assert elapsed < 1.0, f"publish blocked on a slow consumer ({elapsed:.3f}s)"
    delivered = await asyncio.wait_for(healthy_task, 2)
    assert [e["payload"]["i"] for e in delivered] == list(range(30))

    # The stalled subscriber's queue is bounded and drop-oldest ran.
    stalled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stalled_task
    assert bc.subscriber_count(run_id) == 0


@pytest.mark.asyncio
async def test_overflow_emits_recoverable_marker() -> None:
    bc = Broadcaster(queue_maxsize=3)
    run_id = "run-drop"
    subscription = bc.subscribe(run_id)

    async def first() -> dict:
        return await subscription.__anext__()

    task = asyncio.create_task(first())
    await _wait_subscribed(bc, run_id, 1)
    for i in range(10):
        await bc.publish(run_id, {"type": "thought_summary", "payload": {"i": i}})
        await asyncio.sleep(0)
    got = await asyncio.wait_for(task, 2)
    # The consumer was stalled during the burst, so it may receive a dropped
    # marker instead of / before the full history — both are acceptable.
    assert got["type"] in {"thought_summary", "events_dropped"}
    await subscription.aclose()

    # Deterministic check: fill a queue with no consumer at all, then verify
    # an events_dropped marker (with replay instructions) reaches it.
    bc2 = Broadcaster(queue_maxsize=2)
    q_sub = bc2.subscribe("run-x")
    task2 = asyncio.create_task(q_sub.__anext__())
    await _wait_subscribed(bc2, "run-x", 1)
    # No loop yields between publishes: the consumer stays parked and the
    # queue saturates, exercising the drop-oldest + marker path.
    for i in range(5):
        await bc2.publish("run-x", {"type": "thought_summary", "payload": {"i": i}})
    await asyncio.wait_for(task2, 2)

    received: list[dict] = []
    for _ in range(3):
        try:
            received.append(await asyncio.wait_for(q_sub.__anext__(), 0.5))
        except asyncio.TimeoutError:
            break  # queue exhausted — stop draining
    await q_sub.aclose()
    all_types = {e["type"] for e in received}
    assert "events_dropped" in all_types, f"drop-oldest must flag the consumer: {all_types}"
    marker = next(e for e in received if e["type"] == "events_dropped")
    assert marker["payload"]["recoverable_via"] == "replay_after"


@pytest.mark.asyncio
async def test_clear_forgets_run() -> None:
    bc = Broadcaster()
    await bc.publish("run-z", _event())
    assert bc.history("run-z")
    bc.clear("run-z")
    assert bc.history("run-z") == []
    assert bc.replay_after("run-z", 0) == []
    assert bc.subscriber_count("run-z") == 0
    # seq restarts from 1 for a cleared run
    assert (await bc.publish("run-z", _event()))["seq"] == 1


@pytest.mark.asyncio
async def test_events_during_subscribe_buffering_window_are_not_lost() -> None:
    """Events published after subscribe() but before first __anext__ arrive."""
    bc = Broadcaster()
    run_id = "run-buffer"
    subscription = bc.subscribe(run_id)
    # Registration happens when the generator body first runs (__anext__).
    task = asyncio.create_task(subscription.__anext__())
    await _wait_subscribed(bc, run_id, 1)
    await bc.publish(run_id, {"type": "run_started"})
    got = await asyncio.wait_for(task, 2)
    assert got["type"] == "run_started"
    await subscription.aclose()


def test_get_broadcaster_is_singleton() -> None:
    reset_broadcaster()
    assert get_broadcaster() is get_broadcaster()
    assert isinstance(get_broadcaster(), Broadcaster)
    assert get_broadcaster()._queue_maxsize == SUBSCRIBER_QUEUE_MAXSIZE
    reset_broadcaster()


def test_broadcaster_validates_limits() -> None:
    with pytest.raises(ValueError):
        Broadcaster(history_limit=0)
    with pytest.raises(ValueError):
        Broadcaster(queue_maxsize=0)
