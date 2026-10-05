"""Tests for orchestrator.engine: happy path, events, retries, revision, degradation."""

from __future__ import annotations

import asyncio

import pytest

import orchestrator.engine as engine_mod
from orchestrator.agents.base import WorkerError
from orchestrator.engine import RunResult, execute_run
from orchestrator.examples.missions import EXAMPLES
from orchestrator.messages import WorkerOutput

CHURN = EXAMPLES["churn"]


def run(coro):
    return asyncio.run(coro)


PINNED_EVENT_TYPES = {
    "run_started",
    "plan_created",
    "agent_started",
    "thought_summary",
    "tool_call",
    "tool_result",
    "artifact_created",
    "step_completed",
    "agent_finished",
    "run_finished",
    "run_failed",
    "token_update",
}


# ---------------------------------------------------------------------------
# Happy path (mock mode, no dataset)
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_success_status_and_structure(self, collector):
        result = run(
            execute_run(
                mission=CHURN.mission,
                dataset_columns=CHURN.dataset_columns,
                on_event=collector,
            )
        )
        assert isinstance(result, RunResult)
        assert result.status == "succeeded"
        assert result.errors == []

        # Plan: every action subtask completed, revision slot skipped.
        by_id = {entry["id"]: entry for entry in result.plan}
        assert by_id["t1"]["status"] == "completed"
        assert by_id["t3"]["status"] == "completed"
        assert by_id["t3_rev"]["status"] == "skipped"

        # Steps recorded with attempts and summaries.
        assert all(step["attempts"] == 1 for step in result.steps if step["status"] == "completed")
        assert all(step["summary"] for step in result.steps if step["status"] == "completed")

        # Artifacts present, all pinned kinds.
        kinds = {artifact["kind"] for artifact in result.artifacts}
        assert kinds <= {"chart", "table", "text", "prediction", "recommendation",
                         "report_markdown", "report_pdf", "file"}
        assert result.artifacts, "expected at least one artifact"

        # Token accounting: every LLM-driven role has counters + cost.
        per_agent = result.token_usage["per_agent"]
        for role in ("analyst", "forecaster", "critic"):
            assert role in per_agent
            assert per_agent[role]["input_tokens"] > 0
            assert per_agent[role]["cost_usd"] >= 0
        totals = result.token_usage["totals"]
        assert totals["input_tokens"] > 0 and totals["output_tokens"] > 0

        # Honesty: in mock mode the planner is rule-based (no LLM call), so it
        # must NOT appear in the cost meter.
        assert "planner" not in per_agent

        # Report built via orchestrator.report (installed in this venv).
        assert result.report is not None
        assert "executive_summary" in result.report

        result.to_dict()  # JSON-safe round trip must not raise

    def test_event_sequence_and_envelopes(self, collector):
        result = run(
            execute_run(mission=CHURN.mission, dataset_columns=CHURN.dataset_columns, on_event=collector)
        )
        events = collector.events
        assert events, "no events emitted"

        # Envelope shape + monotonic seq starting at 1.
        for index, event in enumerate(events, start=1):
            assert set(event) == {"type", "run_id", "seq", "ts", "agent", "payload"}
            assert event["seq"] == index
            assert event["run_id"] == result.run_id
            assert event["ts"].endswith("Z")

        # Order: run_started first, plan_created second, run_finished last.
        assert events[0]["type"] == "run_started"
        assert events[1]["type"] == "plan_created"
        assert events[-1]["type"] == "run_finished"
        assert events[-1]["payload"] == {"report_ready": True}

        # All event types used by this flow are pinned strings.
        used = set(collector.types)
        assert used <= PINNED_EVENT_TYPES
        for required in (
            "run_started", "plan_created", "agent_started", "thought_summary",
            "artifact_created", "step_completed", "agent_finished", "token_update",
            "run_finished",
        ):
            assert required in used, f"missing {required}"

        # agent_started precedes its step_completed; token_update per agent.
        for event in collector.by_type("agent_started"):
            subtask_id = event["payload"]["subtask_id"]
            later = [e for e in events[events.index(event):] if e["payload"].get("subtask_id") == subtask_id]
            assert any(e["type"] == "agent_finished" for e in later)

    def test_plan_created_payload_schema(self, collector):
        run(execute_run(mission=CHURN.mission, on_event=collector))
        plan_event = collector.by_type("plan_created")[0]
        assert plan_event["agent"] == "planner"
        for subtask in plan_event["payload"]["subtasks"]:
            assert set(subtask) >= {"id", "title", "agent", "depends_on", "status"}

    def test_token_update_payload_schema(self, collector):
        run(execute_run(mission=CHURN.mission, on_event=collector))
        for event in collector.by_type("token_update"):
            assert set(event["payload"]) == {
                "agent", "input_tokens", "output_tokens", "cost_usd", "run_total_usd"
            }
            assert event["agent"] == event["payload"]["agent"]

    def test_no_dataset_still_succeeds(self, collector):
        result = run(execute_run(mission="Research the EV charging market and forecast adoption", on_event=collector))
        assert result.status == "succeeded"


# ---------------------------------------------------------------------------
# Retry path
# ---------------------------------------------------------------------------


class TestRetryPath:
    def test_failed_attempts_retried_then_succeed(self, collector, monkeypatch):
        calls = {"n": 0}
        original_builder = engine_mod._build_workers

        def flaky_builder(llm, registry, hooks):
            workers = original_builder(llm, registry, hooks)
            analyst = workers["analyst"]
            real_run = analyst.run

            async def flaky_run(assignment):
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise WorkerError("injected transient failure")
                return await real_run(assignment)

            analyst.run = flaky_run
            return workers

        monkeypatch.setattr(engine_mod, "_build_workers", flaky_builder)
        result = run(execute_run(mission=CHURN.mission, on_event=collector))

        assert calls["n"] == 3  # 2 failures + success
        step = next(s for s in result.steps if s["subtask_id"] == "t1")
        assert step["attempts"] == 3
        assert result.status == "succeeded"

    def test_permanent_failure_marks_step_failed_and_continues(self, collector, monkeypatch):
        original_builder = engine_mod._build_workers

        def broken_builder(llm, registry, hooks):
            workers = original_builder(llm, registry, hooks)
            analyst = workers["analyst"]

            async def broken_run(assignment):
                raise WorkerError("permanently broken")

            analyst.run = broken_run
            return workers

        monkeypatch.setattr(engine_mod, "_build_workers", broken_builder)
        result = run(execute_run(mission=CHURN.mission, on_event=collector))

        assert result.status == "partial"
        step = next(s for s in result.steps if s["subtask_id"] == "t1")
        assert step["status"] == "failed" and step["attempts"] == 3
        assert any("t1" in error for error in result.errors)
        # Downstream still ran with degraded upstream context.
        by_id = {s["subtask_id"]: s for s in result.steps}
        assert by_id["t2"]["status"] == "completed"
        assert by_id["t3"]["status"] == "completed"
        # agent_finished(ok=False) was emitted.
        assert any(
            e["payload"].get("ok") is False for e in collector.by_type("agent_finished")
        )


# ---------------------------------------------------------------------------
# Critic revision path
# ---------------------------------------------------------------------------


class TestRevisionPath:
    def test_one_revision_pass_then_re_review(self, collector, monkeypatch):
        original_builder = engine_mod._build_workers
        analyst_calls = {"n": 0}
        critic_calls = {"n": 0}

        def revision_builder(llm, registry, hooks):
            workers = original_builder(llm, registry, hooks)

            analyst = workers["analyst"]
            real_analyst_run = analyst.run

            async def counting_analyst(assignment):
                analyst_calls["n"] += 1
                return await real_analyst_run(assignment)

            analyst.run = counting_analyst

            critic = workers["critic"]

            async def scripted_critic_run(assignment):
                critic_calls["n"] += 1
                approved = critic_calls["n"] >= 2
                return WorkerOutput(
                    subtask_id=assignment.subtask_id,
                    role="critic",
                    ok=True,
                    summary="MOCK critic verdict",
                    content={
                        "thought_summary": "MOCK review",
                        "approved": approved,
                        "issues": [] if approved else ["t1 claim unsupported"],
                        "revision_requests": (
                            []
                            if approved
                            else [{
                                "target_subtask_id": "t1",
                                "reason": "claim lacks evidence",
                                "instruction": "attach the stats",
                                "severity": "major",
                            }]
                        ),
                        "final_verdict": "approved" if approved else "revise",
                        "summary": "MOCK critic verdict",
                    },
                )

            critic.run = scripted_critic_run
            return workers

        monkeypatch.setattr(engine_mod, "_build_workers", revision_builder)
        result = run(execute_run(mission=CHURN.mission, on_event=collector))

        # Analyst ran twice (original + revision); critic ran twice (review + re-review).
        assert analyst_calls["n"] == 2
        assert critic_calls["n"] == 2
        assert result.status == "succeeded"
        # Revision slot consumed.
        by_id = {s["subtask_id"]: s for s in result.steps}
        assert by_id["t3_rev"]["status"] == "completed"
        # The revision run was announced as a revision pass.
        titles = [e["payload"]["title"] for e in collector.by_type("agent_started")]
        assert any("(revision pass)" in title for title in titles)

    def test_revision_instruction_reaches_worker_assignment(self, collector, monkeypatch):
        """The flagged worker's revision run carries the critic's instruction."""
        original_builder = engine_mod._build_workers
        seen_instructions: list[str] = []
        critic_calls = {"n": 0}

        def revision_builder(llm, registry, hooks):
            workers = original_builder(llm, registry, hooks)

            analyst = workers["analyst"]
            real_analyst_run = analyst.run

            async def spy_analyst(assignment):
                if assignment.is_revision:
                    seen_instructions.append(assignment.revision_instruction)
                return await real_analyst_run(assignment)

            analyst.run = spy_analyst

            critic = workers["critic"]

            async def scripted_critic_run(assignment):
                critic_calls["n"] += 1
                approved = critic_calls["n"] >= 2
                return WorkerOutput(
                    subtask_id=assignment.subtask_id,
                    role="critic",
                    ok=True,
                    summary="MOCK critic verdict",
                    content={
                        "approved": approved,
                        "issues": [],
                        "revision_requests": (
                            [] if approved
                            else [{"target_subtask_id": "t1", "reason": "weak", "instruction": "add evidence"}]
                        ),
                        "final_verdict": "ok" if approved else "revise",
                        "summary": "MOCK critic verdict",
                    },
                )

            critic.run = scripted_critic_run
            return workers

        monkeypatch.setattr(engine_mod, "_build_workers", revision_builder)
        result = run(execute_run(mission=CHURN.mission, on_event=collector))
        assert result.status == "succeeded"
        assert seen_instructions == ["weak -> add evidence"]


# ---------------------------------------------------------------------------
# Budget / degradation of planning
# ---------------------------------------------------------------------------


class TestBudgetAndHardFailure:
    def test_step_budget_skips_remaining(self, collector):
        result = run(
            execute_run(mission=CHURN.mission, on_event=collector, max_steps=2)
        )
        by_id = {s["subtask_id"]: s for s in result.steps}
        assert by_id["t1"]["status"] == "completed"
        assert by_id["t2"]["status"] == "completed"
        assert by_id["t3"]["status"] == "skipped"
        assert result.status == "partial"
        assert any("budget" in error for error in result.errors)

    def test_empty_mission_fails_at_planning(self, collector):
        result = run(execute_run(mission="   ", on_event=collector))
        assert result.status == "failed"
        assert result.errors
        failed = collector.by_type("run_failed")
        assert failed and failed[0]["payload"]["stage"] == "planning"
        assert collector.types[-1] == "run_failed"

    def test_event_subscriber_crash_does_not_kill_run(self):
        def bad_subscriber(envelope):
            raise RuntimeError("subscriber down")

        result = run(execute_run(mission=CHURN.mission, on_event=bad_subscriber))
        assert result.status == "succeeded"
