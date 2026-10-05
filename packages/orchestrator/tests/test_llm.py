"""Tests for orchestrator.llm: JSON extraction, mock routing, retries/fallback."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from orchestrator.llm import (
    LLMAPIError,
    LLMClient,
    LLMConfig,
    LLMJSONError,
    extract_json,
)


def run(coro):
    """Drive an async call from a sync test (no pytest-asyncio config needed)."""
    return asyncio.run(coro)


def _system(role: str) -> dict:
    return {
        "role": "system",
        "content": f"You are the {role} agent of an AgentForge team. ROLE: {role}.",
    }


def _tools(*names: str) -> list[dict]:
    return [
        {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
        for name in names
    ]


# ---------------------------------------------------------------------------
# extract_json edge cases
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        text = "Sure! Here you go:\n```json\n{\"a\": 1, \"b\": [2, 3]}\n```\nHope that helps."
        assert extract_json(text) == {"a": 1, "b": [2, 3]}

    def test_prose_wrapped_object(self):
        text = 'The plan is: {"subtasks": [{"id": "t1"}]} — let me know if unclear.'
        assert extract_json(text) == {"subtasks": [{"id": "t1"}]}

    def test_top_level_array(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_braces_inside_strings(self):
        text = '{"code": "if (a[b]) { return \\"}\\"; }", "n": 1}'
        assert extract_json(text)["n"] == 1

    def test_trailing_comma_tolerated(self):
        assert extract_json('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}

    def test_garbage_raises(self):
        with pytest.raises(LLMJSONError):
            extract_json("I could not produce any JSON, sorry.")

    def test_empty_raises(self):
        with pytest.raises(LLMJSONError):
            extract_json("")

    def test_none_raises(self):
        with pytest.raises(LLMJSONError):
            extract_json(None)

    def test_nested_object_takes_first_balance(self):
        text = 'prefix {"outer": {"inner": [1, {"deep": 2}]}} suffix {"second": true}'
        assert extract_json(text) == {"outer": {"inner": [1, {"deep": 2}]}}


# ---------------------------------------------------------------------------
# Mock mode: deterministic, offline, labeled
# ---------------------------------------------------------------------------


class TestMockComplete:
    def test_researcher_tool_call_round0(self):
        client = LLMClient()
        messages = [_system("researcher"), {"role": "user", "content": "MISSION: EV chargers"}]
        response = run(client.complete(messages, tools=_tools("web_search")))
        assert response.mock is True
        assert response.wants_tools
        assert response.tool_calls[0].name == "web_search"
        assert response.tool_calls[0].arguments["query"].startswith("EV chargers")
        assert response.usage.input_tokens > 0 and response.usage.output_tokens > 0
        run(client.aclose())

    def test_researcher_final_after_tool_results(self):
        client = LLMClient()
        messages = [
            _system("researcher"),
            {"role": "user", "content": "MISSION: EV chargers"},
            {"role": "assistant", "content": "", "tool_calls": []},
            {"role": "tool", "tool_call_id": "c1", "name": "web_search", "content": "{}"},
        ]
        response = run(client.complete(messages, tools=_tools("web_search")))
        assert not response.wants_tools
        payload = extract_json(response.content)
        assert payload["findings"] and payload["source_urls"]
        assert "MOCK" in payload["summary"]
        run(client.aclose())

    def test_forecaster_final_has_predictions(self):
        client = LLMClient()
        messages = [
            _system("forecaster"),
            {"role": "user", "content": "MISSION: forecast churn\nUPSTREAM RESULTS:\n- SUBTASK t1 (analyst, status=completed): MOCK analysis"},
        ]
        response = run(client.complete(messages))
        payload = extract_json(response.content)
        assert isinstance(payload["predictions"], list) and payload["predictions"]
        first = payload["predictions"][0]
        assert 0.0 <= first["confidence"] <= 1.0 and first["basis"]
        run(client.aclose())

    def test_role_detection_not_hijacked_by_upstream_mentions(self):
        """The forecaster prompt mentions 'analyst' upstream; detection must hold."""
        client = LLMClient()
        messages = [
            _system("forecaster"),
            {"role": "user", "content": "MISSION: m\nUPSTREAM RESULTS:\n- SUBTASK t1 (analyst, status=completed): analyst stuff"},
        ]
        response = run(client.complete(messages))
        payload = extract_json(response.content)
        assert "predictions" in payload  # forecaster contract, not analyst's
        run(client.aclose())

    def test_critic_flags_marked_subtasks(self):
        client = LLMClient()
        messages = [
            _system("critic"),
            {"role": "user", "content": "MISSION: m\n- SUBTASK t2 (analyst): claim [FLAG:t2] unsupported"},
        ]
        response = run(client.complete(messages))
        payload = extract_json(response.content)
        assert payload["approved"] is False
        targets = [r["target_subtask_id"] for r in payload["revision_requests"]]
        assert targets == ["t2"]
        run(client.aclose())

    def test_critic_approves_clean_outputs(self):
        client = LLMClient()
        messages = [_system("critic"), {"role": "user", "content": "MISSION: m\n- SUBTASK t1: fine"}]
        response = run(client.complete(messages))
        payload = extract_json(response.content)
        assert payload["approved"] is True and payload["revision_requests"] == []
        run(client.aclose())

    def test_mock_usage_is_deterministic(self):
        client = LLMClient()
        messages = [_system("analyst"), {"role": "user", "content": "MISSION: m"}]
        first = run(client.complete(messages))
        second = run(client.complete(messages))
        assert first.usage.as_dict() == second.usage.as_dict()
        run(client.aclose())

    def test_mock_never_uses_http_client(self):
        """Mock mode must not create the httpx client (offline guarantee)."""
        client = LLMClient()
        run(client.complete([_system("critic"), {"role": "user", "content": "MISSION: m"}]))
        assert client._client is None
        run(client.aclose())


class TestCompleteJson:
    def test_returns_parsed_dict(self):
        client = LLMClient()
        messages = [_system("planner"), {"role": "user", "content": "MISSION: m"}]
        data = run(client.complete_json(messages, required_keys=["subtasks"]))
        assert isinstance(data, dict) and "subtasks" in data
        run(client.aclose())

    def test_missing_required_key_raises(self):
        client = LLMClient()
        messages = [_system("critic"), {"role": "user", "content": "MISSION: m"}]
        with pytest.raises(LLMJSONError):
            run(client.complete_json(messages, required_keys=["definitely_not_a_key"]))
        run(client.aclose())


# ---------------------------------------------------------------------------
# Live mode: retries, fallback model, usage parsing (via MockTransport)
# ---------------------------------------------------------------------------


def _chat_response(model: str, content: str = '{"ok": true}') -> dict:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content, "tool_calls": []},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 111, "completion_tokens": 22},
        "model": model,
    }


def _make_transport(handler) -> httpx.AsyncBaseTransport:
    return httpx.MockTransport(handler)


def _live_config(model: str = "m1", fallback: str = "m2") -> LLMConfig:
    return LLMConfig(
        base_url="http://llm.test/v1",
        api_key="test-key",
        model=model,
        fallback_model=fallback,
        mode="live",
        timeout_seconds=5,
        max_retries=1,
        backoff_base_seconds=0.0,
    )


class TestLiveMode:
    def test_success_parses_usage_and_headers(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("Authorization")
            seen["url"] = str(request.url)
            body = json.loads(request.content)
            return httpx.Response(200, json=_chat_response(body["model"]))

        client = LLMClient(config=_live_config(), transport=_make_transport(handler))
        response = run(client.complete([{"role": "user", "content": "hi"}]))
        assert response.content == '{"ok": true}'
        assert response.usage.as_dict() == {"input_tokens": 111, "output_tokens": 22}
        assert response.model == "m1"
        assert seen["auth"] == "Bearer test-key"
        assert seen["url"] == "http://llm.test/v1/chat/completions"
        run(client.aclose())

    def test_retry_then_success_on_primary(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(500, text="boom")
            body = json.loads(request.content)
            return httpx.Response(200, json=_chat_response(body["model"]))

        client = LLMClient(config=_live_config(), transport=_make_transport(handler))
        response = run(client.complete([{"role": "user", "content": "hi"}]))
        assert response.model == "m1" and calls["n"] == 2
        run(client.aclose())

    def test_fallback_model_used_when_primary_exhausted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body["model"] == "m1":
                return httpx.Response(503, text="overloaded")
            return httpx.Response(200, json=_chat_response(body["model"]))

        client = LLMClient(config=_live_config(), transport=_make_transport(handler))
        response = run(client.complete([{"role": "user", "content": "hi"}]))
        assert response.model == "m2"
        run(client.aclose())

    def test_all_models_failing_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="down")

        client = LLMClient(config=_live_config(), transport=_make_transport(handler))
        with pytest.raises(LLMAPIError):
            run(client.complete([{"role": "user", "content": "hi"}]))
        run(client.aclose())

    def test_non_retryable_status_goes_to_fallback(self):
        tried = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            tried.append(body["model"])
            if body["model"] == "m1":
                return httpx.Response(401, text="bad key")
            return httpx.Response(200, json=_chat_response(body["model"]))

        client = LLMClient(config=_live_config(), transport=_make_transport(handler))
        response = run(client.complete([{"role": "user", "content": "hi"}]))
        assert tried == ["m1", "m2"] and response.model == "m2"
        run(client.aclose())

    def test_tool_calls_parsed_from_live_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "web_search",
                                            "arguments": '{"query": "ev chargers"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 7},
                    "model": "m1",
                },
            )

        client = LLMClient(config=_live_config(), transport=_make_transport(handler))
        response = run(client.complete([{"role": "user", "content": "hi"}], tools=_tools("web_search")))
        assert response.wants_tools
        assert response.tool_calls[0].arguments == {"query": "ev chargers"}
        run(client.aclose())
