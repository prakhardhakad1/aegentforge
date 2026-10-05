"""orchestrator.memory — pluggable run-memory interface (Agent 3).

v1 ships the interface plus a dependency-free local implementation, per
docs/SPEC.md ("pluggable — ship simple local JSON store + interface for
Pinecone/Qdrant; optional v1.x, interface only").

**No fake cloud calls**: there is deliberately no Pinecone/Qdrant client here.
To add one later, implement :class:`MemoryStore` against the vendor SDK and
swap it in wherever the engine's default store is consumed — the engine only
calls ``save``/``search`` and never assumes the backend.

    class QdrantMemory:            # future adapter, NOT shipped (honesty rules)
        def save(self, run_summary): ...   # upsert vector + payload
        def search(self, query, k=5): ...  # dense similarity search
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = ["MemoryStore", "InMemoryJSONStore"]


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol for pluggable run-memory backends.

    Implementations must be JSON-safe in and out and must never raise on
    *read* paths (return ``[]`` when there are no results). ``save`` may
    raise on I/O failure — the engine treats memory as best-effort.
    """

    def save(self, run_summary: dict[str, Any]) -> str:
        """Persist one run summary; returns its memory id."""
        ...

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Return up to *k* run summaries most relevant to *query*."""
        ...


@dataclass
class _Record:
    """Internal storage record."""

    id: str
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        """Lowercased text blob used for naive lexical scoring."""
        return json.dumps(self.summary, ensure_ascii=False, default=str).lower()


class InMemoryJSONStore:
    """Local run memory: in-process dict with optional JSON file persistence.

    Search is a transparent token-overlap ranking (no vector DB) — good enough
    to recall "similar past runs" in demos and tests. Swap in Pinecone/Qdrant
    adapters behind :class:`MemoryStore` for real semantic recall later.

    Args:
        persist_path: Optional JSON file; when set, the store loads it on
            construction and rewrites it after every :meth:`save`.
    """

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self._records: dict[str, _Record] = {}
        self._lock = threading.Lock()
        self._path = Path(persist_path) if persist_path else None
        if self._path is not None:
            self._load()

    # -- MemoryStore protocol ------------------------------------------------

    def save(self, run_summary: dict[str, Any]) -> str:
        """Persist one run summary (dict, JSON-serializable); returns the id."""
        if not isinstance(run_summary, dict):
            raise TypeError("run_summary must be a dict")
        memory_id = str(run_summary.get("run_id") or f"mem_{uuid.uuid4().hex[:12]}")
        with self._lock:
            self._records[memory_id] = _Record(id=memory_id, summary=run_summary)
            if self._path is not None:
                self._flush()
        logger.debug("Memory: saved run summary %s (%d records)", memory_id, len(self._records))
        return memory_id

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Rank stored summaries by token overlap with *query* (naive lexical)."""
        k = max(0, int(k))
        if k == 0:
            return []
        tokens = set(re.findall(r"[a-z0-9]{3,}", (query or "").lower()))
        with self._lock:
            scored: list[tuple[float, str, dict[str, Any]]] = []
            for record in self._records.values():
                words = set(re.findall(r"[a-z0-9]{3,}", record.searchable_text))
                overlap = len(tokens & words)
                score = overlap / (len(tokens) or 1)
                scored.append((score, record.id, record.summary))
        scored.sort(key=lambda item: (-item[0], item[1]))
        results: list[dict[str, Any]] = []
        for score, _rec_id, summary in scored[:k]:
            hit = dict(summary)
            hit["_score"] = round(score, 4)
            results.append(hit)
        return results

    def count(self) -> int:
        """Number of stored summaries (used by tests)."""
        with self._lock:
            return len(self._records)

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        """Load records from the JSON file, if it exists and parses."""
        assert self._path is not None
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw if isinstance(raw, list) else []:
                if isinstance(item, dict) and item.get("id"):
                    self._records[str(item["id"])] = _Record(
                        id=str(item["id"]), summary=item.get("summary", {})
                    )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Memory store %s unreadable, starting empty: %s", self._path, exc)

    def _flush(self) -> None:
        """Best-effort rewrite of the JSON persistence file."""
        assert self._path is not None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [{"id": r.id, "summary": r.summary} for r in self._records.values()]
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Memory store %s could not be written: %s", self._path, exc)
