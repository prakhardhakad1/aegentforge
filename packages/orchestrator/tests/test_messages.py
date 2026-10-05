"""Tests for orchestrator.messages: dataclass contracts and coercion."""

from __future__ import annotations

from orchestrator.messages import (
    CriticVerdict,
    RevisionRequest,
    TaskAssignment,
    WorkerOutput,
    valid_statuses,
)


class TestTaskAssignment:
    def test_prompt_context_contains_structured_fields(self):
        assignment = TaskAssignment(
            subtask_id="t1",
            title="Analyze",
            role="analyst",
            guidance="profile the data",
            mission="Churn spiked",
            dataset_path="/tmp/x.csv",
            dataset_columns=["a", "b"],
        )
        text = assignment.to_prompt_context()
        assert "MISSION: Churn spiked" in text
        assert "SUBTASK: [t1] Analyze" in text
        assert "ROLE: analyst" in text
        assert "DATASET PATH: /tmp/x.csv" in text
        assert "DATASET COLUMNS: a, b" in text
        assert "GUIDANCE: profile the data" in text

    def test_upstream_and_revision_sections(self):
        assignment = TaskAssignment(
            subtask_id="t2",
            title="Forecast",
            role="forecaster",
            mission="m",
            upstream=[{"subtask_id": "t1", "role": "analyst", "status": "completed",
                       "summary": "stats done", "content": {"stats": {"mean": 3}}}],
            is_revision=True,
            revision_instruction="add evidence",
        )
        text = assignment.to_prompt_context()
        assert "UPSTREAM RESULTS:" in text
        assert "SUBTASK t1 (analyst, status=completed)" in text
        assert "REVISION REQUEST: add evidence" in text


class TestRevisionRequest:
    def test_from_dict_coerces_sloppy_llm_output(self):
        request = RevisionRequest.from_dict(
            {"subtask_id": "t1", "reason": "vague", "fix": "redo it", "severity": "huge"}
        )
        assert request.target_subtask_id == "t1"
        assert request.instruction == "redo it"
        assert request.severity == "major"  # invalid severity normalized

    def test_from_dict_empty_target(self):
        request = RevisionRequest.from_dict({"reason": "x"})
        assert request.target_subtask_id == ""


class TestCriticVerdict:
    def test_roundtrip_dicts(self):
        verdict = CriticVerdict(
            subtask_id="t3",
            approved=False,
            issues=["unsupported"],
            revision_requests=[RevisionRequest("t1", "no evidence", "redo", "major")],
            final_verdict="revise",
            summary="s",
        )
        data = verdict.to_dict()
        assert data["approved"] is False
        assert data["revision_requests"][0]["target_subtask_id"] == "t1"


class TestWorkerOutput:
    def test_to_dict_json_safe(self):
        output = WorkerOutput(subtask_id="t1", role="analyst", ok=True, summary="s")
        data = output.to_dict()
        assert data["ok"] is True and data["content"] == {}


def test_valid_statuses():
    assert set(valid_statuses()) == {"pending", "running", "completed", "failed", "skipped"}
