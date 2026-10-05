"""orchestrator.agents.base — the Worker base class (Agent 3).

Owns everything common to specialists so each role only declares its
contract:

* **Input assembly** — mission, subtask guidance, dataset info and upstream
  digests are rendered into one structured user block
  (``TaskAssignment.to_prompt_context``).
* **Tool loop** — an OpenAI-style function-calling loop: the model requests
  tools, the worker executes them against a (duck-typed) tool registry,
  feeds results back, and repeats up to ``max_tool_rounds``. Tools never
  raise outward; failures become honest ``ok=False`` tool_result events.
* **Structured output** — the final answer must satisfy the role's
  ``required_keys``; parsing goes through the robust
  :func:`orchestrator.llm.extract_json` with a ``complete_json`` retry.
* **Accounting** — every LLM call and tool call is reported through
  :class:`WorkerHooks` so the engine can emit pinned events and token
  updates.
* **Artifacts** — charts/predictions in the structured payload become
  artifact dicts in the pinned ``artifact_created`` shape.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Sequence

from orchestrator.llm import LLMClient, LLMResponse, LLMToolCall, extract_json
from orchestrator.messages import TaskAssignment, WorkerOutput

logger = logging.getLogger(__name__)

__all__ = ["Worker", "WorkerError", "WorkerHooks"]

# duck-typed ToolResult accessors (Agent 4's agentforge_tools.base.ToolResult)
_TOOL_RESULT_MAX_CHARS = 4000
_ARGS_SUMMARY_MAX_CHARS = 140


class WorkerError(RuntimeError):
    """Raised when a worker cannot produce a usable structured output.

    The engine treats this as a failed attempt and applies its per-step
    retry policy.
    """


@dataclass
class WorkerHooks:
    """Engine-provided callbacks a worker uses to report progress.

    ``emit`` receives ``(event_type, agent, payload)`` — the engine wraps it
    into the pinned envelope. ``add_tokens`` receives
    ``(agent, input_tokens, output_tokens)`` and returns the token_update
    payload (the engine emits the event; the return value is informational).
    """

    emit: Callable[[str, str | None, dict[str, Any]], None]
    add_tokens: Callable[[str, int, int], dict[str, Any]]


@dataclass
class Worker:
    """Base class for all specialist agents. Subclasses set the ClassVars."""

    role: ClassVar[str] = "worker"
    title: ClassVar[str] = "Specialist"
    allowed_tools: ClassVar[tuple[str, ...]] = ()
    required_keys: ClassVar[tuple[str, ...]] = ("summary",)
    system_prompt: ClassVar[str] = "You are a helpful business-analysis agent."
    max_tool_rounds: ClassVar[int] = 3
    temperature: ClassVar[float] = 0.4

    llm: LLMClient
    registry: Any = None  # duck-typed agentforge_tools ToolRegistry or None
    hooks: WorkerHooks | None = None

    # -- public entry point ---------------------------------------------------

    async def run(self, assignment: TaskAssignment) -> WorkerOutput:
        """Execute the subtask: tool loop, final structured answer, artifacts.

        Raises:
            WorkerError: no usable structured output was produced (the
                engine's retry policy applies).
        """
        messages = self.build_messages(assignment)
        tool_events: list[dict[str, Any]] = []
        response: LLMResponse | None = None

        for round_index in range(self.max_tool_rounds + 1):
            response = await self._complete_with_accounting(
                messages, tools=self._tool_specs()
            )
            if response.wants_tools and round_index < self.max_tool_rounds:
                messages = self._append_tool_round(
                    messages, assignment, response, tool_events
                )
                continue
            break

        assert response is not None  # loop always runs once
        content = self._final_structured(assignment, messages, response)
        summary = str(content.get("summary") or content.get("thought_summary") or "").strip()
        if not summary:
            raise WorkerError(
                f"{self.role} produced no summary for subtask {assignment.subtask_id}"
            )

        artifacts = self.build_artifacts(assignment, content)
        self._emit_thought(assignment, content)
        for artifact in artifacts:
            self._emit(
                "artifact_created",
                self.role,
                {
                    "subtask_id": assignment.subtask_id,
                    "artifact_id": artifact["artifact_id"],
                    "kind": artifact["kind"],
                    "name": artifact["name"],
                    "summary": artifact.get("summary", ""),
                    **({"path": artifact["path"]} if artifact.get("path") else {}),
                },
            )

        return WorkerOutput(
            subtask_id=assignment.subtask_id,
            role=self.role,
            ok=True,
            summary=summary,
            content=content,
            artifacts=artifacts,
            tool_events=tool_events,
            error=None,
            mock=response.mock,
        )

    # -- context assembly -------------------------------------------------------

    def build_messages(self, assignment: TaskAssignment) -> list[dict[str, Any]]:
        """System prompt + structured user context block."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": assignment.to_prompt_context()},
        ]

    # -- LLM interaction --------------------------------------------------------

    async def _complete_with_accounting(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """One completion with token accounting hooked in."""
        response = await self.llm.complete(
            messages,
            tools=tools,
            temperature=self.temperature,
        )
        if self.hooks is not None:
            self.hooks.add_tokens(
                self.role, response.usage.input_tokens, response.usage.output_tokens
            )
        return response

    def _tool_specs(self) -> list[dict[str, Any]] | None:
        """OpenAI function-calling specs for this role's allowed tools."""
        if self.registry is None or not self.allowed_tools:
            return None
        try:
            specs = self.registry.function_calling_specs()
        except Exception as exc:  # noqa: BLE001 — registry is duck-typed
            logger.warning("registry.function_calling_specs failed: %s", exc)
            return None
        return [
            spec for spec in specs
            if isinstance(spec, dict)
            and spec.get("function", {}).get("name") in self.allowed_tools
        ] or None

    def _append_tool_round(
        self,
        messages: list[dict[str, Any]],
        assignment: TaskAssignment,
        response: LLMResponse,
        tool_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute requested tools, emit events, extend the conversation."""
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.raw_arguments or "{}"},
                }
                for tc in response.tool_calls
            ],
        }
        updated = list(messages) + [assistant_msg]
        for tool_call in response.tool_calls:
            result = self._execute_tool(assignment, tool_call)
            tool_events.append(result)
            updated.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": json.dumps(
                        {
                            "ok": result["ok"],
                            **({"data": result["data"]} if result.get("data") is not None else {}),
                            **({"error": result["error"]} if result.get("error") else {}),
                        },
                        ensure_ascii=False,
                        default=str)[:_TOOL_RESULT_MAX_CHARS],
                }
            )
        return updated

    def _execute_tool(
        self, assignment: TaskAssignment, tool_call: LLMToolCall
    ) -> dict[str, Any]:
        """Run one tool call; emits tool_call/tool_result events. Never raises."""
        args_summary = json.dumps(tool_call.arguments, ensure_ascii=False, default=str)
        if len(args_summary) > _ARGS_SUMMARY_MAX_CHARS:
            args_summary = args_summary[: _ARGS_SUMMARY_MAX_CHARS - 3] + "..."

        allowed = tool_call.name in self.allowed_tools
        if self.registry is None or not allowed:
            self._emit(
                "tool_call",
                self.role,
                {
                    "subtask_id": assignment.subtask_id,
                    "tool": tool_call.name,
                    "args_summary": args_summary,
                    "ok": False,
                },
            )
            error = "tool not available" if not allowed else "no tool registry in this run"
            self._emit(
                "tool_result",
                self.role,
                {
                    "subtask_id": assignment.subtask_id,
                    "tool": tool_call.name,
                    "args_summary": args_summary,
                    "ok": False,
                },
            )
            return {"tool": tool_call.name, "args_summary": args_summary, "ok": False, "error": error}

        self._emit(
            "tool_call",
            self.role,
            {
                "subtask_id": assignment.subtask_id,
                "tool": tool_call.name,
                "args_summary": args_summary,
                "ok": True,
            },
        )
        try:
            result = self.registry.run(tool_call.name, tool_call.arguments)
            ok = bool(getattr(result, "ok", False))
            data = getattr(result, "data", None)
            error = getattr(result, "error", None)
            # Tool-side artifacts (e.g. rendered chart files) ride along.
            for extra in getattr(result, "artifacts", None) or []:
                if isinstance(extra, dict):
                    self._emit_extra_artifact(assignment, extra)
        except Exception as exc:  # noqa: BLE001 — tools must never crash the run
            logger.warning("tool %s crashed: %s", tool_call.name, exc)
            ok, data, error = False, None, f"tool crashed: {exc}"

        self._emit(
            "tool_result",
            self.role,
            {
                "subtask_id": assignment.subtask_id,
                "tool": tool_call.name,
                "args_summary": args_summary,
                "ok": ok,
            },
        )
        return {"tool": tool_call.name, "args_summary": args_summary, "ok": ok,
                "error": error, "data": data}

    def _emit_extra_artifact(self, assignment: TaskAssignment, extra: dict[str, Any]) -> None:
        """Emit an artifact_created event for a tool-produced artifact."""
        artifact_id = str(extra.get("artifact_id") or f"art_{assignment.subtask_id}_tool")
        self._emit(
            "artifact_created",
            self.role,
            {
                "subtask_id": assignment.subtask_id,
                "artifact_id": artifact_id,
                "kind": str(extra.get("kind") or "file"),
                "name": str(extra.get("name") or artifact_id),
                "summary": str(extra.get("summary") or ""),
                **({"path": extra["path"]} if extra.get("path") else {}),
            },
        )

    # -- structured output -------------------------------------------------------

    def _final_structured(
        self,
        assignment: TaskAssignment,
        messages: list[dict[str, Any]],
        response: LLMResponse,
    ) -> dict[str, Any]:
        """Parse + validate the final answer; one corrective retry, then raise."""
        candidates: list[Any] = []
        if response.content:
            try:
                candidates.append(extract_json(response.content))
            except ValueError as exc:
                logger.debug("final content not JSON (%s); falling back", exc)
        parsed: dict[str, Any] | None = next(
            (c for c in candidates if isinstance(c, dict)), None
        )
        if parsed is None:
            try:
                parsed = self.llm.complete_json(
                    messages,
                    required_keys=self.required_keys,
                    schema_hint=self._schema_hint(),
                )
            except ValueError as exc:
                raise WorkerError(
                    f"{self.role} returned no valid JSON for {assignment.subtask_id}: {exc}"
                ) from exc

        missing = [key for key in self.required_keys if key not in parsed]
        if missing:
            raise WorkerError(
                f"{self.role} output for {assignment.subtask_id} missing keys: {missing}"
            )
        return parsed

    def _schema_hint(self) -> str:
        """Human-readable shape hint derived from required keys."""
        return "{" + ", ".join(f"{key}: ..." for key in self.required_keys) + "}"

    # -- artifacts + events --------------------------------------------------------

    def build_artifacts(
        self, assignment: TaskAssignment, content: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert structured payload pieces into pinned artifact dicts.

        Every artifact dict carries ``subtask_id`` so RunResult.artifacts
        matches the ``artifact_created`` event payloads.
        """
        artifacts: list[dict[str, Any]] = []
        counter = 0

        def next_id() -> str:
            nonlocal counter
            counter += 1
            return f"art_{assignment.subtask_id}_{counter}"

        def base_artifact(kind: str, name: str, summary: str, data: dict[str, Any]) -> dict[str, Any]:
            return {
                "artifact_id": next_id(),
                "subtask_id": assignment.subtask_id,
                "kind": kind,
                "name": name,
                "summary": summary,
                "data": data,
            }

        for chart in content.get("charts") or []:
            if isinstance(chart, dict):
                artifacts.append(base_artifact(
                    "chart",
                    str(chart.get("title") or "Chart"),
                    str(chart.get("notes") or ""),
                    chart,
                ))
        for prediction in content.get("predictions") or []:
            if isinstance(prediction, dict):
                claim = str(prediction.get("claim") or "Prediction")
                artifacts.append(base_artifact(
                    "prediction",
                    claim[:80],
                    str(prediction.get("basis") or ""),
                    prediction,
                ))
        findings = content.get("findings")
        if isinstance(findings, Sequence) and not isinstance(findings, str):
            artifacts.append(base_artifact(
                "text",
                f"{self.title} findings",
                str(content.get("summary") or ""),
                {
                    "findings": list(findings),
                    "source_urls": list(content.get("source_urls") or []),
                },
            ))
        insights = content.get("insights")
        if isinstance(insights, Sequence) and not isinstance(insights, str):
            artifacts.append(base_artifact(
                "text",
                f"{self.title} insights",
                str(content.get("summary") or ""),
                {"insights": list(insights)},
            ))
        if not artifacts:
            artifacts.append(base_artifact(
                "text",
                f"{self.title} output",
                str(content.get("summary") or ""),
                dict(content),
            ))
        return artifacts

    def _emit_thought(self, assignment: TaskAssignment, content: dict[str, Any]) -> None:
        """Emit the post-run thought summary (1-2 human-readable sentences)."""
        summary = str(
            content.get("thought_summary")
            or content.get("summary")
            or ""
        ).strip()
        self._emit(
            "thought_summary",
            self.role,
            {"subtask_id": assignment.subtask_id, "summary": summary[:280]},
        )

    def _emit(self, event_type: str, agent: str | None, payload: dict[str, Any]) -> None:
        """Route an event through the engine hooks (no-op without hooks)."""
        if self.hooks is not None:
            self.hooks.emit(event_type, agent, payload)
