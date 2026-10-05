"""orchestrator.engine — the run loop (Agent 3).

    plan -> topological execution (per-step retry <= 2) -> critic review
         -> ONE revision pass for flagged items -> finalize (+ report)

The pinned entrypoint (docs/INTERFACES.md)::

    async def execute_run(
        mission: str,
        template_id: str | None = None,
        dataset_path: str | None = None,
        dataset_columns: list[str] | None = None,
        on_event: Callable[[dict], None] | None = None,
        max_steps: int = 24,
    ) -> RunResult

Every pinned event type is emitted through ``on_event`` as an envelope
``{type, run_id, seq, ts, agent, payload}`` with a run-local monotonic ``seq``
starting at 1.

Honest degradation: a subtask that fails its retries is marked ``failed`` and
recorded in ``errors``; downstream subtasks still run with whatever upstream
digests exist; the final status is ``succeeded`` / ``partial`` / ``failed``
and never overstates what happened.

Test seams (monkeypatch targets, see tests): ``_default_llm_client``,
``_default_tool_registry`` and ``_build_workers`` are module-level functions.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from orchestrator.agents import Worker, WorkerError, WorkerHooks, build_default_workers
from orchestrator.llm import LLMClient
from orchestrator.messages import (
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    SKIPPED,
    CriticVerdict,
    TaskAssignment,
)
from orchestrator.planner import Plan, PlanValidationError, Planner
from orchestrator.tokens import TokenAccountant

logger = logging.getLogger(__name__)

__all__ = ["RunResult", "execute_run"]

EventCallback = Callable[[dict], None]

# Retry policy per subtask (brief: per-step retry <= 2 -> up to 3 attempts).
MAX_ATTEMPTS_PER_STEP = 3
# Cap on subtasks the single revision pass will re-run.
MAX_REVISION_TARGETS = 3


# ---------------------------------------------------------------------------
# RunResult (pinned shape)
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Final outcome of one orchestrated run (JSON-safe via :meth:`to_dict`)."""

    run_id: str
    mission: str
    status: str  # "succeeded" | "partial" | "failed"
    plan: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Pinned JSON-safe dict (docs/INTERFACES.md RunResult shape)."""
        return {
            "run_id": self.run_id,
            "mission": self.mission,
            "status": self.status,
            "plan": self.plan,
            "steps": self.steps,
            "artifacts": self.artifacts,
            "token_usage": self.token_usage,
            "report": self.report,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Test seams (module-level so tests can monkeypatch them)
# ---------------------------------------------------------------------------


def _default_llm_client() -> LLMClient:
    """Build the run's LLM client (env-configured)."""
    return LLMClient()


def _default_tool_registry(run_id: str) -> Any:
    """Build the AgentForge tool registry (Agent 4) when importable.

    The sandbox/files tools share one per-run workspace under the system temp
    dir; no repo directory is written at runtime. Any import/creation failure
    yields ``None`` and workers simply run without tools (honest degradation).
    """
    try:
        import tempfile
        from pathlib import Path

        import agentforge_tools

        workspace = Path(tempfile.gettempdir()) / "agentforge_runs" / run_id[:8]
        return agentforge_tools.build_default_registry(workspace)
    except Exception as exc:  # noqa: BLE001 — tools are optional at runtime
        logger.info("tool registry unavailable, workers run tool-less: %s", exc)
        return None


def _build_workers(
    llm: LLMClient, registry: Any, hooks: WorkerHooks
) -> dict[str, Worker]:
    """Instantiate the role-keyed worker team (monkeypatch target in tests)."""
    return build_default_workers(llm, registry, hooks)


# ---------------------------------------------------------------------------
# Event emitter
# ---------------------------------------------------------------------------


class _Emitter:
    """Builds pinned envelopes and delivers them to ``on_event``."""

    def __init__(self, run_id: str, on_event: EventCallback | None) -> None:
        """One emitter per run; seq starts at 0 and is pre-incremented."""
        self.run_id = run_id
        self.on_event = on_event
        self._seq = 0
        self.envelopes: list[dict[str, Any]] = []

    def emit(self, event_type: str, agent: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        """Emit one event; returns the envelope (seq is strictly monotonic)."""
        self._seq += 1
        envelope = {
            "type": event_type,
            "run_id": self.run_id,
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent": agent,
            "payload": payload,
        }
        self.envelopes.append(envelope)
        if self.on_event is not None:
            try:
                self.on_event(envelope)
            except Exception as exc:  # noqa: BLE001 — a bad subscriber must not kill a run
                logger.warning("on_event callback raised for %s: %s", event_type, exc)
        logger.debug("event %s seq=%d agent=%s payload=%s", event_type, self._seq, agent, payload)
        return envelope


# ---------------------------------------------------------------------------
# Internal run state
# ---------------------------------------------------------------------------


@dataclass
class _StepRecord:
    """Mutable per-subtask execution record."""

    subtask_id: str
    title: str
    agent: str
    status: str = PENDING
    attempts: int = 0
    summary: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe step dict for RunResult.steps."""
        return {
            "subtask_id": self.subtask_id,
            "title": self.title,
            "agent": self.agent,
            "status": self.status,
            "attempts": self.attempts,
            "summary": self.summary,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# execute_run
# ---------------------------------------------------------------------------


async def execute_run(
    mission: str,
    template_id: str | None = None,
    dataset_path: str | None = None,
    dataset_columns: list[str] | None = None,
    on_event: EventCallback | None = None,
    max_steps: int = 24,
) -> RunResult:
    """Orchestrate one full AgentForge run (pinned entrypoint).

    Args:
        mission: the user's one-sentence business goal.
        template_id: optional marketplace template (market_research_team,
            sales_insights_team, support_triage_team).
        dataset_path: optional CSV path for the analyst.
        dataset_columns: optional column names (from the upload API).
        on_event: receives every pinned event envelope as it fires.
        max_steps: budget of worker attempts across the whole run.

    Returns:
        RunResult with the pinned shape; never raises for foreseeable
        failures — hard failures come back as ``status="failed"`` plus a
        ``run_failed`` event.
    """
    run_id = str(uuid.uuid4())
    emitter = _Emitter(run_id, on_event)
    accountant = TokenAccountant.from_env()
    errors: list[str] = []
    artifacts: list[dict[str, Any]] = []
    steps: dict[str, _StepRecord] = {}

    def record_tokens(agent: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
        """Accountant hook: update counters and emit the token_update event."""
        snapshot = accountant.add(agent, input_tokens, output_tokens)
        emitter.emit("token_update", agent, snapshot)
        return snapshot

    hooks = WorkerHooks(
        emit=lambda event_type, agent, payload: emitter.emit(event_type, agent, payload),
        add_tokens=record_tokens,
    )

    mission = (mission or "").strip()
    llm = _default_llm_client()
    registry = _default_tool_registry(run_id)

    emitter.emit(
        "run_started",
        None,
        {
            "mission": mission,
            "template_id": template_id,
            "mode": "mock" if llm.is_mock else "live",
            "has_dataset": bool(dataset_path),
        },
    )

    # -- 1. plan -------------------------------------------------------------
    try:
        planner = Planner(llm, on_usage=lambda i, o: record_tokens("planner", i, o))
        plan: Plan = await planner.plan(
            mission, template_id=template_id, dataset_columns=dataset_columns
        )
    except PlanValidationError as exc:
        return _hard_failure(
            emitter, run_id, mission, f"planning failed: {exc}", "planning", accountant
        )
    except Exception as exc:  # noqa: BLE001 — engine never raises outward
        logger.exception("planning crashed")
        return _hard_failure(
            emitter, run_id, mission, f"planning crashed: {exc}", "planning", accountant
        )

    for sub in plan.subtasks:
        steps[sub.id] = _StepRecord(sub.id, sub.title, sub.agent)
    emitter.emit(
        "plan_created",
        "planner",
        {"subtasks": plan.to_dicts(include_guidance=False), "strategy": plan.strategy},
    )

    workers = _build_workers(llm, registry, hooks)
    outputs: dict[str, Any] = {}
    revision_instructions: dict[str, str] = {}

    def budget_left() -> int:
        """Remaining attempt budget across the run."""
        return max_steps - sum(record.attempts for record in steps.values())

    def upstream_digests(subtask_id: str) -> list[dict[str, Any]]:
        """Digest upstream outputs for the assignment (failures included)."""
        sub = plan.subtask(subtask_id)
        if sub is None:
            return []
        digests: list[dict[str, Any]] = []
        for dep_id in sub.depends_on:
            dep = plan.subtask(dep_id)
            if dep is None:
                continue
            record = steps.get(dep_id)
            output = outputs.get(dep_id)
            digests.append(
                {
                    "subtask_id": dep_id,
                    "role": dep.agent,
                    "title": dep.title,
                    "status": record.status if record else PENDING,
                    "summary": output.summary if output else (record.error if record else ""),
                    "content": output.content if output else {},
                }
            )
        return digests

    async def run_subtask(subtask_id: str, is_revision: bool = False) -> bool:
        """Execute one subtask with the per-step retry policy.

        Returns True when the subtask ended ``completed``. Emits the full
        event set: agent_started, thought_summary, tool events (in worker),
        artifact_created (in worker), agent_finished.
        """
        sub = plan.subtask(subtask_id)
        record = steps[subtask_id]
        record.status = RUNNING
        label = " (revision pass)" if is_revision else ""
        emitter.emit(
            "agent_started",
            sub.agent,
            {"subtask_id": subtask_id, "title": sub.title + label},
        )
        emitter.emit(
            "thought_summary",
            sub.agent,
            {
                "subtask_id": subtask_id,
                "summary": (
                    f"Approach: {sub.guidance[:200]}" if sub.guidance
                    else f"Starting: {sub.title}"
                ),
            },
        )

        last_error = "unknown failure"
        for _attempt in range(MAX_ATTEMPTS_PER_STEP):
            if budget_left() <= 0:
                last_error = "run step budget exhausted"
                break
            record.attempts += 1
            assignment = TaskAssignment(
                subtask_id=subtask_id,
                title=sub.title,
                role=sub.agent,
                guidance=sub.guidance,
                mission=mission,
                template_id=template_id,
                dataset_path=dataset_path,
                dataset_columns=list(dataset_columns or []),
                upstream=upstream_digests(subtask_id),
                is_revision=is_revision,
                revision_instruction=revision_instructions.get(subtask_id, ""),
            )
            try:
                worker = workers.get(sub.agent)
                if worker is None:
                    raise WorkerError(f"no worker for role {sub.agent!r}")
                output = await worker.run(assignment)
                if not output.ok:
                    last_error = output.error or "worker reported failure"
                    continue
            except Exception as exc:  # noqa: BLE001 — failed attempts are recorded
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("subtask %s attempt failed: %s", subtask_id, last_error)
                continue

            outputs[subtask_id] = output
            record.status = COMPLETED
            record.summary = output.summary
            record.error = None
            artifacts.extend(output.artifacts)
            emitter.emit("step_completed", sub.agent, {"subtask_id": subtask_id})
            emitter.emit(
                "agent_finished",
                sub.agent,
                {"subtask_id": subtask_id, "ok": True, "summary": output.summary[:280]},
            )
            return True

        record.status = FAILED
        record.error = last_error
        errors.append(f"subtask {subtask_id} ({sub.agent}) failed: {last_error}")
        emitter.emit(
            "agent_finished",
            sub.agent,
            {"subtask_id": subtask_id, "ok": False, "error": last_error[:280]},
        )
        return False

    # -- 2. topological execution (revision slots handled post-critic) --------
    stage = "execution"
    try:
        for sub in plan.topological_order():
            if sub.is_revision_slot:
                continue
            if budget_left() <= 0:
                sub.status = SKIPPED
                steps[sub.id].status = SKIPPED
                errors.append(f"step budget exhausted; subtask {sub.id} skipped")
                continue
            await run_subtask(sub.id)

        # -- 3. critic review + ONE revision pass ------------------------------
        critic = plan.critic
        if critic is not None and steps[critic.id].status == COMPLETED:
            critic_worker = workers.get("critic")
            critic_output = outputs.get(critic.id)
            if critic_worker is not None and critic_output is not None:
                critic_assignment = TaskAssignment(
                    subtask_id=critic.id,
                    title=critic.title,
                    role="critic",
                    guidance=critic.guidance,
                    mission=mission,
                    template_id=template_id,
                    upstream=upstream_digests(critic.id),
                )
                verdict: CriticVerdict = critic_worker.verdict(critic_output, critic_assignment)

                slots = plan.revision_slots
                targets = [
                    request for request in verdict.revision_requests
                    if request.target_subtask_id in outputs
                    and steps.get(request.target_subtask_id, _StepRecord("", "", "")).status == COMPLETED
                ][: min(MAX_REVISION_TARGETS, len(slots) or MAX_REVISION_TARGETS)]

                if targets and budget_left() > 0:
                    logger.info(
                        "critic flagged %d subtask(s); running ONE revision pass", len(targets)
                    )
                    for request in targets:
                        if budget_left() <= 0:
                            break
                        revision_instructions[request.target_subtask_id] = (
                            f"{request.reason} -> {request.instruction}"
                        )
                        await run_subtask(request.target_subtask_id, is_revision=True)

                    # Re-review once after the revision pass.
                    if budget_left() > 0 and await run_subtask(critic.id):
                        new_output = outputs.get(critic.id)
                        if new_output is not None:
                            try:
                                verdict = critic_worker.verdict(new_output, critic_assignment)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("re-review verdict parse failed: %s", exc)

                for slot in slots:
                    slot.status = COMPLETED if targets else SKIPPED
                    steps[slot.id].status = slot.status
                    if not targets:
                        steps[slot.id].summary = "No revision required by the critic."

                if not verdict.approved and verdict.revision_requests:
                    errors.append(
                        "critic still flags issues after the revision pass: "
                        + "; ".join(r.reason for r in verdict.revision_requests[:3])
                    )

        # Any revision slot left pending (critic failed / no critic) is skipped.
        for slot in plan.revision_slots:
            if steps[slot.id].status == PENDING:
                steps[slot.id].status = SKIPPED
                slot.status = SKIPPED
    except Exception as exc:  # noqa: BLE001 — engine never raises outward
        logger.exception("execution crashed")
        return _hard_failure(emitter, run_id, mission, f"execution crashed: {exc}", stage, accountant)

    # -- 4. finalize ----------------------------------------------------------
    plan_dicts = plan.to_dicts(include_guidance=True)
    for sub in plan.subtasks:
        record = steps[sub.id]
        sub.status = record.status
        for entry in plan_dicts:
            if entry["id"] == sub.id:
                entry["status"] = record.status
                break

    action_records = [steps[s.id] for s in plan.subtasks if not s.is_revision_slot]
    completed = [r for r in action_records if r.status == COMPLETED]
    if not completed:
        status = "failed"
    elif len(completed) == len(action_records):
        status = "succeeded"
    else:
        status = "partial"

    result = RunResult(
        run_id=run_id,
        mission=mission,
        status=status,
        plan=plan_dicts,
        steps=[steps[sid].to_dict() for sid in steps],
        artifacts=artifacts,
        token_usage=accountant.to_dict(),
        report=None,
        errors=errors,
    )

    result.report = _try_build_report(result, template_id)
    if result.report is not None:
        summary_text = str(result.report.get("executive_summary") or "")[:220]
        report_artifact = {
            "artifact_id": f"art_{run_id[:8]}_report",
            "kind": "report_markdown",
            "name": "Final report",
            "summary": summary_text,
            "subtask_id": plan.critic.id if plan.critic else None,
        }
        artifacts.append(report_artifact)
        result.artifacts = artifacts
        emitter.emit(
            "artifact_created",
            None,
            {k: v for k, v in report_artifact.items() if k != "subtask_id"}
            | ({"subtask_id": report_artifact["subtask_id"]} if report_artifact["subtask_id"] else {}),
        )

    _save_run_summary(result)
    emitter.emit("run_finished", None, {"report_ready": result.report is not None})
    logger.info(
        "run %s finished: status=%s steps=%d artifacts=%d cost_usd=%.6f",
        run_id, status, len(result.steps), len(artifacts),
        accountant.total_cost(),
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hard_failure(
    emitter: _Emitter,
    run_id: str,
    mission: str,
    message: str,
    stage: str,
    accountant: TokenAccountant,
) -> RunResult:
    """Emit run_failed and return an honestly-failed RunResult."""
    logger.error("run %s failed at stage %s: %s", run_id, stage, message)
    emitter.emit("run_failed", None, {"error": message[:500], "stage": stage})
    return RunResult(
        run_id=run_id,
        mission=mission,
        status=FAILED,
        token_usage=accountant.to_dict(),
        errors=[message],
    )


def _try_build_report(result: RunResult, template_id: str | None) -> dict[str, Any] | None:
    """Build the structured report via Agent 6's module; None when absent/broken."""
    try:
        from orchestrator.report import build_report  # noqa: PLC0415

        return build_report(result.to_dict(), style=template_id or "default")
    except ImportError:
        logger.info("orchestrator.report not installed yet; report omitted")
        return None
    except Exception as exc:  # noqa: BLE001 — report is best-effort
        logger.warning("build_report failed (%s); report omitted", exc)
        return None


_DEFAULT_MEMORY: Any = None


def _get_default_memory() -> Any:
    """Lazily create the process-wide run-memory store (best-effort)."""
    global _DEFAULT_MEMORY
    if _DEFAULT_MEMORY is None:
        try:
            from orchestrator.memory import InMemoryJSONStore  # noqa: PLC0415

            _DEFAULT_MEMORY = InMemoryJSONStore()
        except Exception as exc:  # noqa: BLE001 — memory is optional
            logger.warning("memory store unavailable: %s", exc)
            _DEFAULT_MEMORY = False  # sentinel: disabled
    return _DEFAULT_MEMORY or None


def _save_run_summary(result: RunResult) -> None:
    """Persist a compact run summary to memory (pluggable; failures ignored)."""
    try:
        memory = _get_default_memory()
        if memory is None:
            return
        memory.save(
            {
                "run_id": result.run_id,
                "mission": result.mission,
                "status": result.status,
                "plan_titles": [s.get("title") for s in result.plan],
                "token_usage": result.token_usage.get("totals", {}),
                "errors": result.errors[:5],
                "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    except Exception as exc:  # noqa: BLE001 — memory must never break a run
        logger.warning("memory save failed: %s", exc)
