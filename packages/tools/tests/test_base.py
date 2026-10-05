"""Tests for the pinned Tool / ToolResult / ToolRegistry contracts (base.py)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentforge_tools.base import (
    Tool,
    ToolInputError,
    ToolRegistry,
    ToolResult,
    json_schema_to_pydantic_model,
)


class EchoTool(Tool):
    """Minimal deterministic tool used to exercise registry behavior."""

    name = "echo"
    description = "Echo the input text back, repeated 'times' times."
    parameters_json_schema: dict = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo."},
            "times": {
                "type": "integer",
                "description": "Repeat count.",
                "default": 1,
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def run(self, inputs: dict) -> ToolResult:
        """Echo ``inputs['text']`` back ``inputs.get('times', 1)`` times."""
        times = int(inputs.get("times", 1))
        text = str(inputs["text"])
        return ToolResult(
            ok=True,
            data={"echo": " ".join([text] * times), "times": times},
        )


class ExplodingTool(Tool):
    """A tool whose run() always raises -- the registry must capture it."""

    name = "explode"
    description = "Always raises RuntimeError."
    parameters_json_schema: dict = {
        "type": "object",
        "properties": {"why": {"type": "string"}},
        "required": [],
        "additionalProperties": False,
    }

    def run(self, inputs: dict) -> ToolResult:
        """Raise unconditionally (registry must convert this to ok=False)."""
        raise RuntimeError(f"boom: {inputs.get('why', 'unspecified')}")


class SchemalessTool(Tool):
    """A tool without a usable parameters_json_schema (dict-ness only)."""

    name = "schemaless"
    description = "No schema."
    parameters_json_schema: dict = {}  # empty -> no validator compiled

    def run(self, inputs: dict) -> ToolResult:
        """Return whatever dict it got."""
        return ToolResult(ok=True, data={"received": inputs})


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

class TestToolResult:
    """ToolResult envelope behavior."""

    def test_to_dict_is_json_serializable(self) -> None:
        """to_dict() must produce something json.dumps can serialize."""
        result = ToolResult(
            ok=True,
            data={"a": 1, "b": [1.5, "x"]},
            artifacts=[{"name": "chart_1", "kind": "bar"}],
        )
        encoded = json.dumps(result.to_dict())
        assert '"ok": true' in encoded

    def test_defaults(self) -> None:
        """A failure result can carry only ok=False + error."""
        result = ToolResult(ok=False, error="nope")
        assert result.data is None
        assert result.artifacts == []
        assert result.to_dict() == {
            "ok": False,
            "data": None,
            "error": "nope",
            "artifacts": [],
        }


# ---------------------------------------------------------------------------
# ToolRegistry: registration + lookup
# ---------------------------------------------------------------------------

class TestRegistryRegistration:
    """register/get/list behavior."""

    def test_register_get_list(self) -> None:
        """Tools are retrievable by name and listed in registration order."""
        registry = ToolRegistry()
        echo = EchoTool()
        explode = ExplodingTool()
        registry.register(echo)
        registry.register(explode)

        assert registry.get("echo") is echo
        assert registry.get("missing") is None
        assert registry.list() == [echo, explode]
        assert registry.names() == ["echo", "explode"]

    def test_duplicate_name_rejected(self) -> None:
        """Registering the same name twice without replace=True raises."""
        registry = ToolRegistry()
        registry.register(EchoTool())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(EchoTool())

    def test_replace_allows_swap(self) -> None:
        """replace=True swaps the implementation under the same name."""
        registry = ToolRegistry()
        first = EchoTool()
        registry.register(first)
        second = EchoTool()
        registry.register(second, replace=True)
        assert registry.get("echo") is second

    def test_non_tool_rejected(self) -> None:
        """register() only accepts Tool instances."""
        registry = ToolRegistry()
        with pytest.raises(TypeError):
            registry.register("not a tool")  # type: ignore[arg-type]

    def test_schemaless_tool_registers_with_warning_only(self) -> None:
        """An empty schema compiles to no validator; inputs pass through."""
        registry = ToolRegistry()
        tool = SchemalessTool()
        registry.register(tool)
        result = registry.run("schemaless", {"anything": [1, 2, 3]})
        assert result.ok is True
        assert result.data == {"received": {"anything": [1, 2, 3]}}


# ---------------------------------------------------------------------------
# ToolRegistry: run() never raises
# ---------------------------------------------------------------------------

class TestRegistryRun:
    """The uniform error-capture contract of ToolRegistry.run."""

    def setup_method(self) -> None:
        """Fresh registry per test."""
        self.registry = ToolRegistry()
        self.registry.register(EchoTool())
        self.registry.register(ExplodingTool())

    def test_happy_path(self) -> None:
        """Valid inputs run the tool and return its result."""
        result = self.registry.run("echo", {"text": "hi", "times": 2})
        assert result.ok is True
        assert result.data == {"echo": "hi hi", "times": 2}

    def test_unknown_tool(self) -> None:
        """Unknown tool names yield ok=False naming the registered tools."""
        result = self.registry.run("nope", {})
        assert result.ok is False
        assert "nope" in (result.error or "")
        assert "echo" in (result.error or "")

    def test_non_dict_inputs(self) -> None:
        """Non-dict inputs are rejected without raising."""
        result = self.registry.run("echo", "just a string")  # type: ignore[arg-type]
        assert result.ok is False
        assert "dict inputs" in (result.error or "")

    def test_none_inputs_means_empty_dict(self) -> None:
        """None inputs are normalized to {} and then fail required-field validation."""
        result = self.registry.run("echo", None)
        assert result.ok is False
        assert "validation failed" in (result.error or "")

    def test_missing_required_field(self) -> None:
        """Missing required 'text' fails schema validation."""
        result = self.registry.run("echo", {"times": 2})
        assert result.ok is False
        assert "text" in (result.error or "")

    def test_wrong_type_field(self) -> None:
        """A string where an integer is declared fails validation."""
        result = self.registry.run("echo", {"text": "hi", "times": "many"})
        assert result.ok is False
        assert "validation failed" in (result.error or "")

    def test_unknown_key_forbidden(self) -> None:
        """additionalProperties: false rejects undeclared keys."""
        result = self.registry.run("echo", {"text": "hi", "bogus": 1})
        assert result.ok is False
        assert "validation failed" in (result.error or "")

    def test_tool_exception_captured(self) -> None:
        """An exception inside run() becomes ok=False, never propagates."""
        result = self.registry.run("explode", {"why": "testing"})
        assert result.ok is False
        assert "RuntimeError" in (result.error or "")
        assert "boom: testing" in (result.error or "")

    def test_default_value_applied(self) -> None:
        """Schema defaults flow into validation (times defaults to 1)."""
        result = self.registry.run("echo", {"text": "hi"})
        assert result.ok is True
        assert result.data == {"echo": "hi", "times": 1}

    def test_coercion_of_declared_types(self) -> None:
        """Pydantic coerces '2' -> 2 for declared integer fields."""
        result = self.registry.run("echo", {"text": "hi", "times": "2"})
        assert result.ok is True
        assert result.data == {"echo": "hi hi", "times": 2}


# ---------------------------------------------------------------------------
# function-calling specs
# ---------------------------------------------------------------------------

class TestFunctionCallingSpecs:
    """Registry -> LLM function-calling spec export."""

    def test_specs_shape(self) -> None:
        """Each registered tool becomes an OpenAI-style function spec."""
        registry = ToolRegistry()
        registry.register(EchoTool())
        specs = registry.function_calling_specs()
        assert specs == [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": EchoTool.description,
                    "parameters": EchoTool.parameters_json_schema,
                },
            }
        ]


# ---------------------------------------------------------------------------
# JSON Schema -> pydantic compilation
# ---------------------------------------------------------------------------

class TestJsonSchemaCompilation:
    """json_schema_to_pydantic_model behavior across schema features."""

    def test_rejects_non_object_schema(self) -> None:
        """Non-object / non-dict schemas are developer errors."""
        with pytest.raises(ToolInputError):
            json_schema_to_pydantic_model("bad", {"type": "array"})
        with pytest.raises(ToolInputError):
            json_schema_to_pydantic_model("bad", "nope")  # type: ignore[arg-type]

    def test_rejects_empty_properties(self) -> None:
        """A schema without properties cannot produce a validator."""
        with pytest.raises(ToolInputError):
            json_schema_to_pydantic_model("bad", {"type": "object"})

    def test_enum_becomes_literal(self) -> None:
        """enum properties only accept the declared values."""
        model = json_schema_to_pydantic_model(
            "enum_model",
            {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]}},
                "required": ["mode"],
            },
        )
        assert model.model_validate({"mode": "fast"}).mode == "fast"
        with pytest.raises(Exception):  # noqa: B017 - pydantic.ValidationError
            model.model_validate({"mode": "turbo"})

    def test_any_of_nullable(self) -> None:
        """anyOf [number, null] accepts numbers and None."""
        model = json_schema_to_pydantic_model(
            "nullable_model",
            {
                "type": "object",
                "properties": {
                    "score": {"anyOf": [{"type": "number"}, {"type": "null"}]}
                },
                "required": ["score"],
            },
        )
        assert model.model_validate({"score": 1.5}).score == 1.5
        assert model.model_validate({"score": None}).score is None

    def test_array_items(self) -> None:
        """Array schemas map to list[inner] and validate items."""
        model = json_schema_to_pydantic_model(
            "array_model",
            {
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["tags"],
            },
        )
        assert model.model_validate({"tags": ["a", "b"]}).tags == ["a", "b"]

    def test_nested_object(self) -> None:
        """Nested object schemas compile into nested pydantic models."""
        model = json_schema_to_pydantic_model(
            "nested_model",
            {
                "type": "object",
                "properties": {
                    "spec": {
                        "type": "object",
                        "properties": {"kind": {"type": "string"}},
                        "required": ["kind"],
                    }
                },
                "required": ["spec"],
            },
        )
        validated = model.model_validate({"spec": {"kind": "bar"}})
        assert validated.spec.kind == "bar"  # type: ignore[union-attr]

    def test_non_required_field_defaults_to_none(self) -> None:
        """Optional fields default to None when absent."""
        model = json_schema_to_pydantic_model(
            "opt_model",
            {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": [],
            },
        )
        assert model.model_validate({}).note is None

    def test_schema_default_honored(self) -> None:
        """A schema 'default' becomes the field default."""
        model = json_schema_to_pydantic_model(
            "default_model",
            {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 5}
                },
                "required": [],
            },
        )
        assert model.model_validate({}).limit == 5

    def test_annotation_from_unknown_is_any(self) -> None:
        """Unrecognized schema fragments degrade to Any rather than crashing."""
        from agentforge_tools.base import _annotation_from_schema

        assert _annotation_from_schema({"type": "weird"}, "m") is Any
        assert _annotation_from_schema("not-a-dict", "m") is Any

    def test_bool_is_accepted_for_integer_in_lax_mode(self) -> None:
        """Documented pydantic lax-mode behavior: bool coerces to int (True->1).

        Input validation is a gate for LLM-generated arguments, not a security
        boundary, so lax coercion is acceptable; tools re-check critical values.
        """
        model = json_schema_to_pydantic_model(
            "int_model",
            {
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
        )
        assert model.model_validate({"n": True}).n == 1
