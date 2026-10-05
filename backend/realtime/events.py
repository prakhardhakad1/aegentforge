"""Canonical AgentForge event system (Agent 7).

This module is the single source of truth for the pinned event envelope
(docs/INTERFACES.md § "Event envelope"):

    {"type": "<event_type>", "run_id": "uuid", "seq": 12,
     "ts": "2026-10-05T12:00:00Z", "agent": "analyst", "payload": {}}

It provides:

* the pinned string constants: :data:`EVENT_TYPES`, :data:`AGENT_ROLES`,
  :data:`ARTIFACT_KINDS` (byte-identical to the values in
  ``app/schemas/common.py`` — kept duplicated so ``realtime`` stays
  dependency-free and importable without the FastAPI app);
* pydantic models for the envelope and for every pinned event payload;
* :func:`make_event` — validated envelope constructor;
* :func:`validate_event` / :func:`validate_event_dict` — validation helpers.

Design notes
------------
* Only ``pydantic`` (and the stdlib) is imported here — no app/ imports — so
  the orchestrator engine, the simulator and tests can all rely on this module
  without pulling in the backend app package.
* Payload models allow extra keys (``extra="allow"``): producers (orchestrator,
  demo simulator) may annotate events (e.g. ``"simulated": true``) without
  breaking validation, while the pinned required fields are still enforced.
* ``make_event`` returns a plain ``dict`` — the canonical in-memory currency
  everywhere else (broadcaster, WS, DB persistence) is a dict, not a model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("agentforge.realtime.events")

# ── Pinned string constants (docs/INTERFACES.md — do not edit values) ────

#: Exact event-type strings.
EVENT_TYPES: tuple[str, ...] = (
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
)

#: Exact agent-role strings (``agent`` field must be one of these or ``None``).
AGENT_ROLES: tuple[str, ...] = ("planner", "researcher", "analyst", "forecaster", "critic")

#: Exact artifact-kind strings for ``artifact_created.payload.kind``.
ARTIFACT_KINDS: tuple[str, ...] = (
    "chart",
    "table",
    "text",
    "prediction",
    "recommendation",
    "report_markdown",
    "report_pdf",
    "file",
)

#: Legal ChartSpec ``kind`` values (docs/INTERFACES.md § "Chart spec").
CHART_KINDS: tuple[str, ...] = ("bar", "line", "scatter", "pie")

_EVENT_TYPE_SET: frozenset[str] = frozenset(EVENT_TYPES)
_AGENT_ROLE_SET: frozenset[str] = frozenset(AGENT_ROLES)
_ARTIFACT_KIND_SET: frozenset[str] = frozenset(ARTIFACT_KINDS)


class EventValidationError(ValueError):
    """Raised when an event violates the pinned envelope/payload contracts."""


# ── Timestamp helper ─────────────────────────────────────────────────────


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp with a ``Z`` suffix (pinned envelope format)."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def is_iso_utc_ts(value: Any) -> bool:
    """Return True when ``value`` parses as an ISO-8601 timestamp.

    Both ``...Z`` and explicit-offset forms are accepted; the pinned format
    ends in ``Z`` and producers should use :func:`utc_now_iso`.
    """
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


# ── Payload models ───────────────────────────────────────────────────────


class _AllowExtra(BaseModel):
    """Base for payload models: pinned fields enforced, extras tolerated."""

    model_config = ConfigDict(extra="allow")


class SubtaskSpec(_AllowExtra):
    """One node of the planner DAG (``plan_created.payload.subtasks[i]``)."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    agent: str  # must be a pinned role
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"

    @field_validator("agent")
    @classmethod
    def _agent_is_role(cls, value: str) -> str:
        if value not in _AGENT_ROLE_SET:
            raise EventValidationError(
                f"subtask.agent must be one of {AGENT_ROLES}, got {value!r}"
            )
        return value


class RunStartedPayload(_AllowExtra):
    """``run_started`` payload (shape not pinned beyond this; extras allowed)."""

    mission: Optional[str] = None
    mode: Optional[str] = None
    simulated: Optional[bool] = None


class PlanCreatedPayload(_AllowExtra):
    """``plan_created`` → ``{"subtasks": [SubtaskSpec, ...]}``."""

    subtasks: list[SubtaskSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _deps_reference_known_ids(self) -> "PlanCreatedPayload":
        ids = {s.id for s in self.subtasks}
        for subtask in self.subtasks:
            for dep in subtask.depends_on:
                if dep not in ids:
                    raise EventValidationError(
                        f"subtask {subtask.id!r} depends_on unknown id {dep!r}"
                    )
        return self


class AgentStartedPayload(_AllowExtra):
    """``agent_started`` → ``{"subtask_id","title"}``."""

    subtask_id: str = Field(min_length=1)
    title: str = Field(min_length=1)


class ThoughtSummaryPayload(_AllowExtra):
    """``thought_summary`` → ``{"subtask_id","summary"}``."""

    subtask_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class ToolPayload(_AllowExtra):
    """Shared by ``tool_call`` and ``tool_result``."""

    subtask_id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    args_summary: str = ""
    ok: bool = True


class ArtifactCreatedPayload(_AllowExtra):
    """``artifact_created`` → pinned fields plus optional ``path``/``data``.

    ``data`` is an Agent 7 extension carrying the structured artifact body
    (a ChartSpec dict for ``chart`` artifacts, ``{"columns","rows"}`` for
    ``table`` artifacts, a report dict for ``report_markdown``) so the live
    artifact feed can render rich previews. Documented in NOTES.md.
    """

    subtask_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    kind: str
    name: str = Field(min_length=1)
    summary: str = ""
    path: Optional[str] = None
    data: Optional[dict[str, Any]] = None

    @field_validator("kind")
    @classmethod
    def _kind_is_pinned(cls, value: str) -> str:
        if value not in _ARTIFACT_KIND_SET:
            raise EventValidationError(
                f"artifact kind must be one of {ARTIFACT_KINDS}, got {value!r}"
            )
        return value


class StepCompletedPayload(_AllowExtra):
    """``step_completed`` → ``{"subtask_id"}``."""

    subtask_id: str = Field(min_length=1)


class TokenUpdatePayload(_AllowExtra):
    """``token_update`` → per-update token/cost deltas plus the run total."""

    agent: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    run_total_usd: float = Field(ge=0)

    @field_validator("agent")
    @classmethod
    def _agent_is_role(cls, value: str) -> str:
        if value not in _AGENT_ROLE_SET:
            raise EventValidationError(
                f"token_update.agent must be one of {AGENT_ROLES}, got {value!r}"
            )
        return value

    @field_validator("input_tokens", "output_tokens", mode="before")
    @classmethod
    def _reject_bool_tokens(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise EventValidationError("token counts must be integers, not bools")
        return value


class AgentFinishedPayload(_AllowExtra):
    """``agent_finished`` → ``{"subtask_id"}`` (subtask_id tolerated optional)."""

    subtask_id: Optional[str] = None


class RunFinishedPayload(_AllowExtra):
    """``run_finished`` → ``{"report_ready": true}``."""

    report_ready: bool = True


class RunFailedPayload(_AllowExtra):
    """``run_failed`` → ``{"error","stage"}``."""

    error: str = Field(min_length=1)
    stage: str = Field(min_length=1)


#: Payload model per pinned event type (``run_started``/``agent_finished`` are
#: permissive because their shapes are not fully pinned).
EVENT_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "run_started": RunStartedPayload,
    "plan_created": PlanCreatedPayload,
    "agent_started": AgentStartedPayload,
    "thought_summary": ThoughtSummaryPayload,
    "tool_call": ToolPayload,
    "tool_result": ToolPayload,
    "artifact_created": ArtifactCreatedPayload,
    "step_completed": StepCompletedPayload,
    "agent_finished": AgentFinishedPayload,
    "run_finished": RunFinishedPayload,
    "run_failed": RunFailedPayload,
    "token_update": TokenUpdatePayload,
}


# ── Envelope model ───────────────────────────────────────────────────────


class EventEnvelope(_AllowExtra):
    """The pinned event envelope (validated; extras tolerated)."""

    type: str
    run_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    ts: str
    agent: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type_is_pinned(cls, value: str) -> str:
        if value not in _EVENT_TYPE_SET:
            raise EventValidationError(
                f"event type must be one of {EVENT_TYPES}, got {value!r}"
            )
        return value

    @field_validator("seq", mode="before")
    @classmethod
    def _reject_bool_seq(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise EventValidationError("seq must be an integer, not a bool")
        return value

    @field_validator("ts")
    @classmethod
    def _ts_is_iso(cls, value: str) -> str:
        if not is_iso_utc_ts(value):
            raise EventValidationError(
                f"ts must be an ISO-8601 timestamp, got {value!r}"
            )
        return value

    @field_validator("agent")
    @classmethod
    def _agent_is_role_or_none(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in _AGENT_ROLE_SET:
            raise EventValidationError(
                f"agent must be one of {AGENT_ROLES} or None, got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _payload_matches_type(self) -> "EventEnvelope":
        payload_model = EVENT_PAYLOAD_MODELS.get(self.type)
        if payload_model is not None:
            try:
                payload_model.model_validate(self.payload)
            except EventValidationError:
                raise
            except Exception as exc:  # pydantic ValidationError → uniform error
                raise EventValidationError(
                    f"payload for {self.type!r} is invalid: {exc}"
                ) from exc
        return self


# ── Constructors / validators ────────────────────────────────────────────


def make_event(
    event_type: str,
    run_id: str,
    seq: int,
    agent: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
    *,
    ts: Optional[str] = None,
) -> dict[str, Any]:
    """Build a fully validated pinned envelope as a plain dict.

    Args:
        event_type: one of :data:`EVENT_TYPES`.
        run_id: the run this event belongs to.
        seq: per-run monotonic sequence number (starts at 1).
        agent: pinned agent role or ``None`` for run-level events.
        payload: payload dict (validated against the pinned schema).
        ts: optional ISO-8601 UTC timestamp; defaults to now.

    Returns:
        The canonical envelope dict.

    Raises:
        EventValidationError: if any field or the payload violates the
            pinned contracts.
    """
    envelope: dict[str, Any] = {
        "type": event_type,
        "run_id": run_id,
        "seq": seq,
        "ts": ts or utc_now_iso(),
        "agent": agent,
        "payload": dict(payload or {}),
    }
    # Round-trip through the model: rejects bad types/agents/payloads. Pydantic
    # wraps validator-raised ValueErrors, so re-wrap into the contract's
    # EventValidationError to give callers one uniform exception type.
    try:
        EventEnvelope.model_validate(envelope)
    except EventValidationError:
        raise
    except Exception as exc:  # pydantic.core.ValidationError and friends
        raise EventValidationError(str(exc)) from exc
    return envelope


def validate_event(event: Any) -> EventEnvelope:
    """Validate an arbitrary object as a pinned event; return the model.

    Raises:
        EventValidationError: on any contract violation (with a uniform
            message prefix so callers can log one consistent error).
    """
    if isinstance(event, EventEnvelope):
        return event
    if not isinstance(event, Mapping):
        raise EventValidationError(
            f"event must be a mapping, got {type(event).__name__}"
        )
    try:
        return EventEnvelope.model_validate(dict(event))
    except EventValidationError:
        raise
    except Exception as exc:
        raise EventValidationError(f"invalid event envelope: {exc}") from exc


def validate_event_dict(event: Any) -> dict[str, Any]:
    """Validate an event and return it unchanged as a plain dict.

    Convenience for producers that deal in dicts (broadcaster, WS layer).
    """
    return validate_event(event).model_dump()


def is_valid_event(event: Any) -> bool:
    """Non-raising validity check (logs at debug level on failure)."""
    try:
        validate_event(event)
        return True
    except EventValidationError as exc:
        logger.debug("Event rejected: %s", exc)
        return False


def chart_spec(
    spec_id: str,
    kind: str,
    title: str,
    x_label: str,
    y_label: str,
    data: list[dict[str, Any]],
    notes: str = "",
) -> dict[str, Any]:
    """Build a pinned ChartSpec dict (docs/INTERFACES.md § "Chart spec").

    Raises:
        EventValidationError: if ``kind`` is not one of :data:`CHART_KINDS`
            or ``data`` is not a non-empty list of label/x/y points.
    """
    if kind not in CHART_KINDS:
        raise EventValidationError(
            f"chart kind must be one of {CHART_KINDS}, got {kind!r}"
        )
    points: list[dict[str, Any]] = []
    for i, point in enumerate(data):
        if not isinstance(point, Mapping):
            raise EventValidationError(f"chart data[{i}] must be a mapping")
        if "y" not in point:
            raise EventValidationError(f"chart data[{i}] missing 'y'")
        points.append(
            {
                "label": str(point.get("label", f"point_{i}")),
                "x": point.get("x", i),
                "y": point.get("y"),
            }
        )
    if not points:
        raise EventValidationError("chart data must contain at least one point")
    spec: dict[str, Any] = {
        "id": spec_id,
        "kind": kind,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "data": points,
    }
    if notes:
        spec["notes"] = notes
    return spec


__all__ = [
    "AGENT_ROLES",
    "ARTIFACT_KINDS",
    "AGENT_ROLE_SET",
    "ARTIFACT_KIND_SET",
    "CHART_KINDS",
    "EVENT_PAYLOAD_MODELS",
    "EVENT_TYPES",
    "EVENT_TYPE_SET",
    "EventEnvelope",
    "EventValidationError",
    "AgentFinishedPayload",
    "AgentStartedPayload",
    "ArtifactCreatedPayload",
    "PlanCreatedPayload",
    "RunFailedPayload",
    "RunFinishedPayload",
    "RunStartedPayload",
    "StepCompletedPayload",
    "SubtaskSpec",
    "ThoughtSummaryPayload",
    "TokenUpdatePayload",
    "ToolPayload",
    "chart_spec",
    "is_iso_utc_ts",
    "is_valid_event",
    "make_event",
    "utc_now_iso",
    "validate_event",
    "validate_event_dict",
]
