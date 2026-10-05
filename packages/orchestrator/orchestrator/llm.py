"""orchestrator.llm — provider-agnostic OpenAI-compatible LLM client (Agent 3).

One client powers the whole pipeline (planner + workers). Design goals:

* **Provider agnostic** — any OpenAI-compatible ``/chat/completions`` endpoint
  (GLM/Zhipu, OpenAI, vLLM, Ollama+openai bridge, ...). Base URL, model, API
  key and timeout come from env vars; nothing is hardcoded (SPEC.md).
* **Mock mode is a feature** — ``LLM_MODE=mock`` returns deterministic canned
  responses, every one clearly labeled ``MOCK``, so the entire
  planner -> workers -> critic pipeline runs fully offline for tests and
  demos. No network call is ever made in mock mode.
* **Resilience** — transient failures (timeouts, 429, 5xx) are retried with
  exponential backoff on the primary model, then the whole attempt set is
  repeated once on ``LLM_FALLBACK_MODEL`` before giving up.
* **Structured output** — :meth:`LLMClient.complete_json` robustly extracts
  JSON from chatty model output (code fences, prose prefixes, trailing text)
  and optionally validates it against a required-keys contract.
* **Token accounting** — every response carries a
  :class:`Usage` (input/output tokens) which the engine feeds to the
  TokenAccountant for the pinned ``token_update`` events and cost meter.

Env vars (canonical names from docs/INTERFACES.md):
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL,
    LLM_MODE (live|mock), LLM_TIMEOUT_SECONDS.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "LLMConfig",
    "Usage",
    "LLMToolCall",
    "LLMResponse",
    "LLMClient",
    "LLMAPIError",
    "LLMJSONError",
    "extract_json",
    "ROLES",
]

# Agent roles (exact strings pinned in docs/INTERFACES.md). The mock responder
# routes its canned payloads on these.
ROLES: tuple[str, ...] = ("planner", "researcher", "analyst", "forecaster", "critic")

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMAPIError(RuntimeError):
    """Raised when every live-mode attempt (primary + fallback) fails."""


class LLMJSONError(ValueError):
    """Raised when a JSON completion cannot be extracted or parsed."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to *default* on absent/garbage."""
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to *default* on absent/garbage."""
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LLMConfig:
    """Resolved LLM provider settings. Build with :meth:`from_env`."""

    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    api_key: str = ""
    model: str = "glm-4-flash"
    fallback_model: str = "glm-4-flash"
    mode: str = "mock"  # "live" | "mock"
    timeout_seconds: float = 60.0
    max_retries: int = 2  # retries per model after the first attempt
    backoff_base_seconds: float = 0.75

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load configuration from the canonical LLM_* environment variables."""
        mode = os.environ.get("LLM_MODE", "mock").strip().lower()
        if mode not in ("live", "mock"):
            logger.warning("LLM_MODE=%r is not live|mock; defaulting to mock", mode)
            mode = "mock"
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", cls.base_url).rstrip("/"),
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", cls.model),
            fallback_model=os.environ.get("LLM_FALLBACK_MODEL", cls.fallback_model),
            mode=mode,
            timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", cls.timeout_seconds),
            max_retries=_env_int("LLM_MAX_RETRIES", cls.max_retries),
        )


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Token usage for one LLM call (what the cost meter is fed)."""

    input_tokens: int
    output_tokens: int

    def as_dict(self) -> dict[str, int]:
        """JSON-safe dict."""
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass(frozen=True)
class LLMToolCall:
    """One function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe dict."""
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass(frozen=True)
class LLMResponse:
    """Normalized completion: text and/or tool calls plus usage."""

    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: Usage = Usage(input_tokens=0, output_tokens=0)
    model: str = ""
    finish_reason: str = "stop"
    mock: bool = False
    latency_ms: int = 0

    @property
    def wants_tools(self) -> bool:
        """True when the model asked for tool invocations."""
        return bool(self.tool_calls)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Extract the first JSON value (object or array) from *text*.

    Robust against the usual LLM quirks: `````json` fences, prose prefixes
    ("Here is the JSON you asked for:"), trailing commentary after the value,
    and smart-quote noise around the payload.

    Raises:
        LLMJSONError: when no parseable JSON object/array is present.
    """
    if text is None:
        raise LLMJSONError("empty LLM response")
    candidates: list[str] = []

    # 1) Fenced blocks first — highest signal.
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    # 2) Raw text (handles unfenced pure-JSON answers).
    candidates.append(text.strip())

    # 3) Balanced-brace scan for JSON embedded in prose. We scan for the first
    #    '{' or '[' and walk to its matching close, respecting string literals
    #    and escapes.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for idx in range(start, len(text)):
                ch = text[idx]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start : idx + 1])
                        break
            start = text.find(opener, start + 1)

    for candidate in candidates:
        if not candidate:
            continue
        # Tolerate smart quotes / trailing commas from sloppy models.
        normalized = candidate.replace("“", '"').replace("”", '"').replace("’", "'")
        normalized = re.sub(r",(\s*[}\]])", r"\1", normalized)
        try:
            return json.loads(normalized)
        except (json.JSONDecodeError, ValueError):
            continue

    raise LLMJSONError(f"no parseable JSON found in response: {text[:200]!r}")


def _estimate_tokens(messages: Sequence[dict[str, Any]], output_text: str) -> Usage:
    """Deterministic ~4-chars-per-token estimate used in mock mode."""
    total_chars = sum(len(str(m.get("content") or "")) for m in messages)
    return Usage(
        input_tokens=max(1, total_chars // 4),
        output_tokens=max(1, len(output_text) // 4),
    )


# ---------------------------------------------------------------------------
# Mock responder — deterministic canned completions, labeled MOCK
# ---------------------------------------------------------------------------

_FLAG_RE = re.compile(r"\[FLAG:([A-Za-z0-9_\-]+)\]")


def _detect_role(messages: Sequence[dict[str, Any]]) -> str | None:
    """Find the agent role the way workers declare it: 'ROLE: <role>' first.

    The strict marker pass (on the system message only) prevents upstream
    mentions of other roles in the user content from hijacking detection.
    """
    system = next((m for m in messages if m.get("role") == "system"), None)
    system_text = str((system or {}).get("content") or "").lower()
    for role in ROLES:
        if re.search(rf"role:\s*{role}\b", system_text):
            return role
    # Fallbacks: role word anywhere in the system prompt, then anywhere at all.
    if system_text:
        for role in ROLES:
            if re.search(rf"\b{role}\b", system_text):
                return role
    text = " ".join(str(m.get("content") or "") for m in messages).lower()
    for role in ROLES:
        if re.search(rf"\b{role}\b", text):
            return role
    return None


def _has_tool_messages(messages: Sequence[dict[str, Any]]) -> bool:
    """True when the conversation already contains tool results."""
    return any(m.get("role") == "tool" for m in messages)


def _extract_field(text: str, label: str) -> str:
    """Pull a 'LABEL: value' line out of a prompt (workers format context so)."""
    match = re.search(rf"^{re.escape(label)}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _columns_from_text(text: str) -> list[str]:
    """Parse 'DATASET COLUMNS: a, b, c' from a worker prompt."""
    raw = _extract_field(text, "DATASET COLUMNS")
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()][:6]


def _mock_tool_call(
    role: str | None, tools: Sequence[dict[str, Any]], user_text: str, call_id: str
) -> LLMToolCall | None:
    """Choose a deterministic tool call for round 0 of the worker loop."""
    tool_names = [
        spec.get("function", {}).get("name", "")
        for spec in tools
        if isinstance(spec, dict)
    ]
    if role == "researcher" and "web_search" in tool_names:
        query = _extract_field(user_text, "MISSION") or "business research"
        return LLMToolCall(
            id=call_id,
            name="web_search",
            arguments={"query": query[:90], "max_results": 5},
            raw_arguments=json.dumps({"query": query[:90], "max_results": 5}),
        )
    if role == "analyst" and "csv_analyzer" in tool_names:
        path = _extract_field(user_text, "DATASET PATH")
        if path:  # no dataset in context -> go straight to the final answer
            args = {"path": path, "question": _extract_field(user_text, "MISSION")[:120]}
            return LLMToolCall(
                id=call_id,
                name="csv_analyzer",
                arguments=args,
                raw_arguments=json.dumps(args),
            )
    return None


def _mock_final_json(role: str | None, user_text: str) -> dict[str, Any]:
    """Deterministic, clearly-labeled canned structured output per role.

    Every payload is prefixed/suffixed with MOCK markers so no one can mistake
    demo output for real research (honesty rules, docs/SPEC.md).
    """
    mission = _extract_field(user_text, "MISSION") or "the mission"
    short = mission if len(mission) <= 110 else mission[:107] + "..."
    mock_note = "MOCK canned response — not real model output"

    if role == "planner":
        return {
            "thought_summary": f"MOCK: drafting a specialist plan for: {short}",
            "subtasks": [
                {
                    "id": "t1",
                    "title": "MOCK: research context",
                    "agent": "researcher",
                    "depends_on": [],
                    "guidance": "MOCK: gather background and benchmarks.",
                },
                {
                    "id": "t2",
                    "title": "MOCK: analyze the data",
                    "agent": "analyst",
                    "depends_on": ["t1"],
                    "guidance": "MOCK: profile the dataset, find drivers.",
                },
                {
                    "id": "t3",
                    "title": "MOCK: forecast outlook",
                    "agent": "forecaster",
                    "depends_on": ["t2"],
                    "guidance": "MOCK: project the key metric forward.",
                },
                {
                    "id": "t4",
                    "title": "MOCK: critical review",
                    "agent": "critic",
                    "depends_on": ["t1", "t2", "t3"],
                    "guidance": "MOCK: verify claims, request revisions.",
                },
            ],
        }

    if role == "researcher":
        return {
            "thought_summary": f"MOCK: searched and synthesized context for: {short}",
            "findings": [
                f"MOCK finding 1: the mission '{short}' maps to a known business pattern.",
                "MOCK finding 2: public benchmarks suggest monitoring the top 3 drivers weekly.",
                "MOCK finding 3: comparable teams saw the fastest wins from low-effort fixes first.",
            ],
            "source_urls": [
                "https://example.com/mock-source/1",
                "https://example.com/mock-source/2",
            ],
            "summary": f"MOCK research summary for: {short}. {mock_note}.",
        }

    if role == "analyst":
        columns = _columns_from_text(user_text)
        metric = columns[1] if len(columns) > 1 else "metric"
        breakdown = columns[0] if columns else "segment"
        return {
            "thought_summary": f"MOCK: profiled the dataset behind: {short}",
            "stats": {
                "rows_examined": 42,
                "columns": columns or ["mock_col_a", "mock_col_b"],
                "metric_mean": 12.5,
                "metric_max": 31.0,
            },
            "insights": [
                f"MOCK insight: '{metric}' moves sharply in the latest period.",
                f"MOCK insight: one '{breakdown}' segment drives most of the change.",
            ],
            "charts": [
                {
                    "id": "chart_1",
                    "kind": "line",
                    "title": f"MOCK: {metric} over time",
                    "x_label": breakdown,
                    "y_label": metric,
                    "data": [
                        {"label": "P1", "x": 1, "y": 8},
                        {"label": "P2", "x": 2, "y": 11},
                        {"label": "P3", "x": 3, "y": 19},
                        {"label": "P4", "x": 4, "y": 26},
                    ],
                    "notes": mock_note,
                },
                {
                    "id": "chart_2",
                    "kind": "bar",
                    "title": f"MOCK: {metric} by {breakdown}",
                    "x_label": breakdown,
                    "y_label": metric,
                    "data": [
                        {"label": "Alpha", "x": 1, "y": 30},
                        {"label": "Beta", "x": 2, "y": 12},
                        {"label": "Gamma", "x": 3, "y": 6},
                    ],
                    "notes": mock_note,
                },
            ],
            "summary": f"MOCK analysis of '{metric}' for: {short}. {mock_note}.",
        }

    if role == "forecaster":
        return {
            "thought_summary": f"MOCK: projected the key trend for: {short}",
            "predictions": [
                {
                    "claim": f"MOCK: the headline metric for '{short}' trends up next period.",
                    "confidence": 0.62,
                    "basis": "MOCK linear extrapolation of the latest trend (canned demo data).",
                },
                {
                    "claim": "MOCK: a focused fix within 2 weeks bends the trend down.",
                    "confidence": 0.54,
                    "basis": "MOCK scenario assumption, not measured (canned demo data).",
                },
            ],
            "summary": f"MOCK forecast for: {short}. {mock_note}.",
        }

    if role == "critic":
        flags = _FLAG_RE.findall(user_text)
        revision_requests = [
            {
                "target_subtask_id": flag,
                "reason": "MOCK: claim lacks supporting evidence (flagged for demo).",
                "instruction": "MOCK: re-run with the specific evidence attached.",
                "severity": "major",
            }
            for flag in flags
        ]
        return {
            "thought_summary": "MOCK: reviewed all artifacts and step outputs.",
            "approved": not revision_requests,
            "issues": [
                "MOCK issue: canned worker outputs are labeled MOCK and must not be quoted as real data."
            ]
            + [
                f"MOCK issue: output of subtask {flag} is unsupported."
                for flag in flags
            ],
            "revision_requests": revision_requests,
            "final_verdict": (
                "MOCK: revisions required." if revision_requests else "MOCK: approved for reporting."
            ),
            "summary": "MOCK critic verdict. " + mock_note + ".",
        }

    # Unknown role: generic canned JSON so the pipeline can still proceed.
    return {
        "thought_summary": f"MOCK: processed subtask for: {short}",
        "summary": f"MOCK generic output for: {short}. {mock_note}.",
    }


def _mock_complete(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> LLMResponse:
    """Produce the deterministic mock completion for this conversation state.

    Round 0 with tools offered -> one tool call (when a tool makes sense);
    after tool results (or with no tools) -> the canned final JSON payload.
    """
    role = _detect_role(messages)
    user_text = "\n".join(
        str(m.get("content") or "") for m in messages if m.get("role") == "user"
    )

    if tools and not _has_tool_messages(messages):
        call = _mock_tool_call(role, tools, user_text, call_id="call_mock_1")
        if call is not None:
            usage = _estimate_tokens(messages, call.raw_arguments)
            return LLMResponse(
                content=None,
                tool_calls=[call],
                usage=usage,
                model="mock-canned",
                finish_reason="tool_calls",
                mock=True,
            )

    payload = _mock_final_json(role, user_text)
    content = json.dumps(payload, ensure_ascii=False)
    # Wrap in a fence on purpose: exercises the JSON extractor every run.
    content = f"```json\n{content}\n```"
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=_estimate_tokens(messages, content),
        model="mock-canned",
        finish_reason="stop",
        mock=True,
    )


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


class LLMClient:
    """Async OpenAI-compatible chat client with mock mode and fallback model.

    Args:
        config: Resolved settings; defaults to :meth:`LLMConfig.from_env`.
        transport: Optional ``httpx.AsyncBaseTransport`` (tests inject
            ``httpx.MockTransport``; production leaves this as ``None``).
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or LLMConfig.from_env()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        # Most recent response (any mode) — lets callers without per-call
        # hooks (e.g. the planner) still read token usage after the fact.
        self.last_response: LLMResponse | None = None

    # -- lifecycle ----------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily create (and reuse) the underlying HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        """Release the underlying HTTP client, if one was created."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- public API ---------------------------------------------------------

    @property
    def is_mock(self) -> bool:
        """True when running in offline mock mode (never touches network)."""
        return self.config.mode == "mock"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
        max_tokens: int = 1600,
    ) -> LLMResponse:
        """Run one chat completion (with tool specs when *tools* is given).

        In mock mode this never performs I/O. In live mode it retries
        transient failures with exponential backoff on the primary model and
        then on the fallback model.

        Raises:
            LLMAPIError: live mode, every attempt exhausted.
        """
        if self.is_mock:
            response = _mock_complete(messages, tools)
        else:
            response = await self._complete_live(messages, tools, temperature, max_tokens)
        self.last_response = response
        return response

    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        required_keys: Sequence[str] | None = None,
        schema_hint: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        max_corrections: int = 1,
    ) -> dict[str, Any]:
        """Ask for a JSON object and robustly extract/validate it.

        Appends a strict JSON instruction, extracts with :func:`extract_json`,
        and (optionally) checks that all *required_keys* are present. On
        failure it retries once with a corrective user message before raising.

        Raises:
            LLMJSONError: no valid JSON object after the correction round.
        """
        contract = (
            f"Respond with a single JSON object and nothing else."
            + (f" It must be valid JSON with keys: {', '.join(required_keys)}." if required_keys else "")
            + (f" Shape hint: {schema_hint}" if schema_hint else "")
        )
        convo: list[dict[str, Any]] = list(messages) + [
            {"role": "user", "content": contract}
        ]

        last_error: Exception | None = None
        for attempt in range(max_corrections + 1):
            response = await self.complete(
                convo, tools=None, temperature=temperature, max_tokens=max_tokens
            )
            try:
                data = extract_json(response.content or "")
            except LLMJSONError as exc:
                last_error = exc
            else:
                if isinstance(data, dict):
                    missing = [k for k in (required_keys or []) if k not in data]
                    if not missing:
                        return data
                    last_error = LLMJSONError(f"JSON missing required keys: {missing}")
                else:
                    last_error = LLMJSONError(
                        f"expected a JSON object, got {type(data).__name__}"
                    )
            if attempt < max_corrections:
                convo.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous reply was not usable: {last_error}. "
                            "Reply again with ONLY a valid JSON object."
                        ),
                    }
                )

        raise LLMJSONError(str(last_error))

    # -- live plumbing ------------------------------------------------------

    async def _complete_live(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Live request path: primary model attempts, then fallback model."""
        models: list[str] = [self.config.model]
        if self.config.fallback_model and self.config.fallback_model != self.config.model:
            models.append(self.config.fallback_model)

        errors: list[str] = []
        for index, model in enumerate(models):
            try:
                return await self._attempt_model(
                    model, messages, tools, temperature, max_tokens
                )
            except (httpx.HTTPError, LLMAPIError) as exc:
                errors.append(f"model={model}: {exc}")
                logger.warning("LLM attempt failed (%s); trying next option", exc)
                if index < len(models) - 1:
                    await self._sleep_backoff(0)

        raise LLMAPIError("all LLM attempts failed: " + " | ".join(errors))

    async def _attempt_model(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """One model's attempt set: initial call + configured retries."""
        last_error: Exception = LLMAPIError("no attempt made")
        for attempt in range(self.config.max_retries + 1):
            started = time.monotonic()
            try:
                return await self._post_chat(model, messages, tools, temperature, max_tokens)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status in _RETRYABLE_STATUS
                last_error = exc
                logger.warning(
                    "LLM HTTP %s from %s (attempt %d, retryable=%s)",
                    status, model, attempt + 1, retryable,
                )
                if not retryable:
                    raise LLMAPIError(
                        f"{model} returned non-retryable HTTP {status}: {exc.response.text[:300]}"
                    ) from exc
            except httpx.HTTPError as exc:  # timeouts, connect errors, etc.
                last_error = exc
                logger.warning("LLM transport error on %s (attempt %d): %s", model, attempt + 1, exc)

            if attempt < self.config.max_retries:
                await self._sleep_backoff(attempt)

        raise LLMAPIError(
            f"{model} failed after {self.config.max_retries + 1} attempts: {last_error}"
        )

    async def _post_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Single HTTP round trip against ``{base_url}/chat/completions``."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        client = self._get_client()
        response = await client.post(
            f"{self.config.base_url}/chat/completions",
            json=body,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage_raw = data.get("usage") or {}
        content = message.get("content")
        if isinstance(content, list):  # some providers return content parts
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        tool_calls: list[LLMToolCall] = []
        for raw in message.get("tool_calls") or []:
            try:
                function = raw.get("function") or {}
                raw_args = function.get("arguments") or "{}"
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                logger.warning("Dropping unparseable tool call: %s", exc)
                continue
            tool_calls.append(
                LLMToolCall(
                    id=str(raw.get("id") or f"call_{len(tool_calls)}"),
                    name=str(function.get("name") or "unknown"),
                    arguments=args if isinstance(args, dict) else {},
                    raw_arguments=raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
                )
            )

        usage = Usage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        )
        if usage.input_tokens == 0 and usage.output_tokens == 0:
            usage = _estimate_tokens(messages, str(content or ""))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=str(data.get("model") or model),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            mock=False,
        )

    async def _sleep_backoff(self, attempt: int) -> None:
        """Exponential backoff between retries (deterministic, no jitter)."""
        import asyncio

        delay = self.config.backoff_base_seconds * (2 ** attempt)
        logger.debug("Backoff %.2fs before retry (attempt %d)", delay, attempt)
        await asyncio.sleep(delay)
