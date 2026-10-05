"""Tests for orchestrator.memory: InMemoryJSONStore save/search/persistence."""

from __future__ import annotations

import json

import pytest

from orchestrator.memory import InMemoryJSONStore, MemoryStore


@pytest.fixture()
def store() -> InMemoryJSONStore:
    return InMemoryJSONStore()


def _summary(run_id: str, mission: str, status: str = "succeeded") -> dict:
    return {"run_id": run_id, "mission": mission, "status": status}


class TestSaveAndSearch:
    def test_save_returns_id_and_counts(self, store):
        memory_id = store.save(_summary("run-1", "Analyze churn in Q3"))
        assert memory_id == "run-1"
        assert store.count() == 1

    def test_search_ranks_by_overlap(self, store):
        store.save(_summary("run-churn", "Analyze customer churn spike and recommend fixes"))
        store.save(_summary("run-ev", "Research the EV fast-charging market"))
        hits = store.search("churn spike fixes", k=2)
        assert hits and hits[0]["run_id"] == "run-churn"
        assert hits[0]["_score"] > hits[1]["_score"]

    def test_search_k_limits_results(self, store):
        for index in range(5):
            store.save(_summary(f"run-{index}", f"mission number {index}"))
        assert len(store.search("mission", k=3)) == 3

    def test_search_k_zero_returns_empty(self, store):
        store.save(_summary("run-1", "mission"))
        assert store.search("mission", k=0) == []

    def test_search_empty_store_returns_empty(self, store):
        assert store.search("anything") == []

    def test_save_requires_dict(self, store):
        with pytest.raises(TypeError):
            store.save("not a dict")  # type: ignore[arg-type]

    def test_store_satisfies_protocol(self, store):
        assert isinstance(store, MemoryStore)


class TestPersistence:
    def test_roundtrip_through_json_file(self, tmp_path):
        path = tmp_path / "memory.json"
        first = InMemoryJSONStore(persist_path=path)
        first.save(_summary("run-1", "churn analysis mission"))
        first.save(_summary("run-2", "ev market research"))
        assert path.exists()

        second = InMemoryJSONStore(persist_path=path)
        assert second.count() == 2
        hits = second.search("ev market", k=1)
        assert hits[0]["run_id"] == "run-2"

    def test_corrupt_file_starts_empty(self, tmp_path):
        path = tmp_path / "memory.json"
        path.write_text("{not json", encoding="utf-8")
        store = InMemoryJSONStore(persist_path=path)
        assert store.count() == 0

    def test_file_content_is_json_list(self, tmp_path):
        path = tmp_path / "memory.json"
        store = InMemoryJSONStore(persist_path=path)
        store.save(_summary("run-1", "m"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, list) and payload[0]["id"] == "run-1"
