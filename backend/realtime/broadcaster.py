"""Per-run in-memory event bus — the full Broadcaster implementation (Agent 7).

Pinned contract (docs/INTERFACES.md § "Module import contracts"; consumers
include ``app/api/routes/runs.py`` and ``app/services/events.py``):

    from realtime.broadcaster import get_broadcaster
    bc = get_broadcaster()
    await bc.publish(run_id, event)          # also accepts publish(event)
    async for event in bc.subscribe(run_id): ...
    bc.history(run_id) -> list[dict]
    bc.replay_after(run_id, seq) -> list[dict]
    bc.clear(run_id)

Guarantees
----------
* **Seq ownership**: ``publish`` stamps ``seq`` only when the event does not
  already carry a valid one (int >= 1). A caller-provided seq (e.g. the
  orchestrator engine's or the demo player's) is preserved verbatim so the
  broadcaster never renumbers or reorders another owner's sequence.
* **Monotonicity under concurrency**: internally stamped seqs come from a
  per-run ``itertools.count`` incremented inside a synchronous (await-free)
  section of :meth:`Broadcaster.publish`, so two concurrent publishers can
  never interleave between "read counter" and "append history" — seqs stay
  unique and strictly increasing, and history order == seq order.
* **Slow-consumer isolation**: every subscriber gets its own *bounded* queue
  (:data:`SUBSCRIBER_QUEUE_MAXSIZE`, drop-oldest). Publishing never awaits on
  a consumer: if a subscriber falls behind, its oldest queued events are
  dropped and it is flagged (``event["payload"]`` untouched — a synthetic
  ``{"type": "events_dropped", ...}`` marker is enqueued instead, see
  :meth:`Broadcaster._offer`). One stalled WebSocket therefore cannot block
  the run or the other subscribers. Missed events are recoverable via
  ``replay_after`` (that is what the client ``{"type":"replay","after_seq":N}``
  message is for).
* **Bounded memory**: per-run history is capped at
  :data:`DEFAULT_HISTORY_LIMIT` events (drop-oldest). ``clear(run_id)``
  releases everything for a finished run.
* **Never raises on the hot path**: fan-out failures are contained per
  subscriber; :meth:`publish` always returns the canonical stamped dict.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import defaultdict
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional

from realtime.events import utc_now_iso

logger = logging.getLogger("agentforge.realtime.broadcaster")

#: Default cap on remembered events per run (replay window).
DEFAULT_HISTORY_LIMIT: int = 2000

#: Per-subscriber queue bound. A consumer slower than this drops oldest events
#: (which it can re-fetch via replay_after) rather than blocking the producer.
SUBSCRIBER_QUEUE_MAXSIZE: int = 512

#: Max number of runs remembered at once (guards against unbounded run keys).
DEFAULT_MAX_RUNS: int = 500


def _valid_seq(value: Any) -> bool:
    """True when ``value`` is a usable event seq (int >= 1, not bool)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


class Broadcaster:
    """Per-run in-memory event bus with bounded history and bounded fan-out.

    See the module docstring for the full behavioural contract. One instance
    is shared process-wide via :func:`get_broadcaster`.
    """

    def __init__(
        self,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        *,
        queue_maxsize: int = SUBSCRIBER_QUEUE_MAXSIZE,
        max_runs: int = DEFAULT_MAX_RUNS,
    ) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be >= 1")
        if queue_maxsize < 1:
            raise ValueError("queue_maxsize must be >= 1")
        self._history_limit = history_limit
        self._queue_maxsize = queue_maxsize
        self._max_runs = max_runs
        # run_id -> event list (bounded, drop-oldest)
        self._history: Dict[str, List[dict]] = {}
        # run_id -> list of subscriber queues (each bounded, drop-oldest)
        self._queues: Dict[str, List["asyncio.Queue[dict]"]] = defaultdict(list)
        # run_id -> seq counter for events published WITHOUT their own seq
        self._counters: Dict[str, itertools.count] = defaultdict(itertools.count)
        # Monotonic per-run high-water mark so explicitly-seq'd events never
        # collide with counter-stamped ones.
        self._seq_watermark: Dict[str, int] = {}

    # ── publishing ───────────────────────────────────────────────────────

    async def publish(self, run_id: Any, event: Optional[dict] = None) -> dict:
        """Publish one event to a run's history and all live subscribers.

        Supports both pinned call shapes:
          * ``await bc.publish(run_id, event)``  (canonical)
          * ``await bc.publish(event)``          (event carries ``run_id``)

        The event's own ``seq`` is preserved when valid (int >= 1); otherwise
        a monotonic per-run seq is stamped. ``ts`` / ``run_id`` are stamped
        when missing. Returns the canonical stamped dict that was stored and
        fanned out — callers (e.g. ``app.services.events``) persist exactly
        this copy.
        """
        # Single-argument form: publish(event)
        if event is None:
            if not isinstance(run_id, Mapping):
                raise TypeError(
                    "publish() requires (run_id, event) or (event) with event.run_id"
                )
            event = dict(run_id)
            rid = event.get("run_id")
            if not isinstance(rid, str) or not rid:
                raise ValueError("publish(event) requires event['run_id']")
            run_id = rid
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(event, Mapping):
            raise TypeError(f"event must be a mapping, got {type(event).__name__}")

        stamped = self._stamp(run_id, dict(event))
        self._remember(run_id, stamped)
        self._fan_out(run_id, stamped)
        return stamped

    def _stamp(self, run_id: str, event: dict) -> dict:
        """Fill in run_id / seq / ts where missing or invalid.

        Synchronous on purpose: no awaits between counter read and history
        append, so concurrent publishers on one loop cannot interleave.
        """
        event["run_id"] = run_id
        seq = event.get("seq")
        if not _valid_seq(seq):
            counter = self._counters[run_id]
            watermark = self._seq_watermark.get(run_id, 0)
            # Skip any seqs already claimed by explicit-seq publishers so the
            # auto-stamped stream never collides or goes backwards.
            seq = max(next(counter), watermark + 1)
            self._seq_watermark[run_id] = seq
            event["seq"] = seq
        elif seq > self._seq_watermark.get(run_id, 0):
            self._seq_watermark[run_id] = seq
        if not isinstance(event.get("ts"), str) or not event.get("ts"):
            event["ts"] = utc_now_iso()
        if "payload" not in event or not isinstance(event["payload"], dict):
            event["payload"] = {}
        if "agent" not in event:
            event["agent"] = None
        return event

    def _remember(self, run_id: str, event: dict) -> None:
        """Append to the bounded per-run history (drop-oldest)."""
        self._enforce_run_budget(run_id)
        history = self._history.setdefault(run_id, [])
        history.append(event)
        overflow = len(history) - self._history_limit
        if overflow > 0:
            del history[:overflow]

    def _enforce_run_budget(self, run_id: str) -> None:
        """Evict the oldest fully-idle run when over the run budget."""
        if run_id in self._history or len(self._history) < self._max_runs:
            return
        for oldest in list(self._history):
            if not self._queues.get(oldest):
                del self._history[oldest]
                self._counters.pop(oldest, None)
                self._seq_watermark.pop(oldest, None)
                break

    def _fan_out(self, run_id: str, event: dict) -> None:
        """Deliver to every live subscriber queue; never blocks or raises."""
        for queue in list(self._queues.get(run_id, ())):
            self._offer(queue, event)

    @staticmethod
    def _offer(queue: "asyncio.Queue[dict]", event: dict) -> None:
        """Non-blocking put with a drop-oldest policy on overflow.

        When the queue is saturated, the oldest queued event is discarded to
        make room for the new one, and a synthetic ``events_dropped`` marker
        is then guaranteed a slot (dropping one more oldest event if needed)
        so the consumer always learns it missed events and can
        ``replay_after`` to recover.
        """
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            if not Broadcaster._force_put(queue, event):
                return  # pragma: no cover - could not make room at all
            marker = {
                "type": "events_dropped",
                "run_id": event.get("run_id"),
                "seq": event.get("seq"),
                "ts": event.get("ts"),
                "agent": None,
                "payload": {"count": 1, "recoverable_via": "replay_after"},
            }
            if not Broadcaster._force_put(queue, marker):  # pragma: no cover
                logger.warning("Could not enqueue events_dropped marker")

    @staticmethod
    def _force_put(queue: "asyncio.Queue[dict]", item: dict) -> bool:
        """put_nowait after evicting oldest entries; False only if impossible."""
        for _ in range(64):  # bounded retries: never spin forever
            try:
                queue.put_nowait(item)
                return True
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # drop the oldest queued event
                except asyncio.QueueEmpty:  # pragma: no cover - raced a consumer
                    return False
        return False  # pragma: no cover - defensive

    # ── subscribing ──────────────────────────────────────────────────────

    async def subscribe(self, run_id: str) -> AsyncIterator[dict]:
        """Yield every event published to ``run_id`` from subscription time on.

        Usage (as the WS route does)::

            subscription = broadcaster.subscribe(run_id)
            try:
                async for event in subscription:
                    await websocket.send_text(json.dumps(event))
            finally:
                await subscription.aclose()

        Events published between ``subscribe()`` and the first ``__anext__``
        are buffered (bounded queue) so nothing is lost. Unsubscribing is
        clean: closing/aborting the generator removes the queue via ``finally``
        even on cancellation.
        """
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues[run_id].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            try:
                subscribers = self._queues.get(run_id)
                if subscribers is not None:
                    try:
                        subscribers.remove(queue)
                    except ValueError:  # pragma: no cover - already removed
                        pass
                    if not subscribers:
                        self._queues.pop(run_id, None)
            except Exception:  # pragma: no cover - unsubscribe must never raise
                logger.exception("Error while unsubscribing from run %s", run_id)

    # ── history / replay ─────────────────────────────────────────────────

    def history(self, run_id: str) -> List[dict]:
        """All remembered events for ``run_id`` in seq order (defensive copy)."""
        return list(self._history.get(run_id, ()))

    def replay_after(self, run_id: str, seq: int) -> List[dict]:
        """Events with ``seq`` strictly greater than ``seq`` (replay window).

        Handles the WS client message ``{"type":"replay","after_seq":N}``.
        Invalid/missing seqs in history are treated as seq 0 (always replayed).
        """
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            seq = 0
        replayed: List[dict] = []
        for event in self._history.get(run_id, ()):
            event_seq = event.get("seq")
            if _valid_seq(event_seq) and event_seq > seq:
                replayed.append(event)
        return replayed

    # ── lifecycle ────────────────────────────────────────────────────────

    def clear(self, run_id: str) -> None:
        """Forget a run's history, counters and watermark (subscribers too).

        Live subscriber queues are closed out by enqueuing a sentinel-free
        removal: we simply detach them; pending events in a removed queue are
        dropped (the client re-syncs via history/replay on reconnect).
        """
        self._history.pop(run_id, None)
        self._counters.pop(run_id, None)
        self._seq_watermark.pop(run_id, None)
        self._queues.pop(run_id, None)

    def subscriber_count(self, run_id: str) -> int:
        """Number of live subscribers for ``run_id`` (introspection/testing)."""
        return len(self._queues.get(run_id, ()))

    def drop_empty_runs(self) -> int:
        """Evict history for runs with no subscribers; returns count freed."""
        freed = 0
        for run_id in list(self._history):
            if not self._queues.get(run_id):
                self.clear(run_id)
                freed += 1
        return freed


_broadcaster: Optional[Broadcaster] = None


def get_broadcaster() -> Broadcaster:
    """Return the process-wide broadcaster singleton (lazily created)."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = Broadcaster()
    return _broadcaster


def reset_broadcaster() -> None:
    """Discard the singleton (tests only — next get_broadcaster() is fresh)."""
    global _broadcaster
    _broadcaster = None


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_MAX_RUNS",
    "SUBSCRIBER_QUEUE_MAXSIZE",
    "Broadcaster",
    "get_broadcaster",
    "reset_broadcaster",
]
