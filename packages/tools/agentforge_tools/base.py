"""Pinned tool contracts for AgentForge.

This module defines the interfaces every AgentForge tool and every agent-side
caller codes against (see ``docs/INTERFACES.md``):

* :class:`Tool` -- abstract base class every tool implements.
* :class:`ToolResult` -- uniform, JSON-serializable return envelope.
* :class:`ToolRegistry` -- named registry that validates tool inputs against
  each tool's ``parameters_json_schema`` (via pydantic) before calling
  ``run()`` and guarantees that tool execution never raises outward.

Design rules enforced here:

* ``ToolRegistry.run`` NEVER raises. Every failure mode (unknown tool, bad
  input, exception inside a tool) is captured as ``ToolResult(ok=False,
  error=...)`` so agents can branch on ``ok`` without try/except.
* Input validation is generic: each tool publishes a JSON Schema (the same
  schema handed to the LLM for function calling) and the registry compiles it
  into a pydantic model at registration time.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

import pydantic
from pydantic import ConfigDict, Field, ValidationError, create_model

logger = logging.getLogger(__name__)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "ToolInputError",
    "json_schema_to_pydantic_model",
]


class ToolInputError(ValueError):
    """Raised when a tool's declared JSON Schema itself cannot be compiled.

    This is a developer error (bad schema), not a user-input error, so it is
    allowed to propagate out of :meth:`ToolRegistry.register`.
    """


@dataclass
class ToolResult:
    """Uniform result envelope returned by every tool.

    Attributes:
        ok: Whether the tool completed its job successfully.
        data: JSON-serializable payload (``None`` when there is nothing to
            report or when the tool failed before producing output).
        error: Human-readable error description when ``ok`` is False.
        artifacts: List of artifact dicts. Convention: rendered charts carry
            pinned ``ChartSpec`` dicts; file-producing tools carry dicts with
            ``name``/``path``/``kind`` keys.
    """

    ok: bool
    data: dict | None = None
    error: str | None = None
    artifacts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict of this result."""
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "artifacts": self.artifacts,
        }


class Tool(ABC):
    """Abstract base class for all AgentForge tools.

    Subclasses MUST set :attr:`name`, :attr:`description` and
    :attr:`parameters_json_schema` as class attributes and implement
    :meth:`run`.

    Contract for ``run`` implementations:

    * Accept a plain ``dict`` of inputs (already validated when called via a
      registry; tools should still be defensive).
    * NEVER raise for expected failure modes -- return
      ``ToolResult(ok=False, error="...")`` instead.
    * Everything placed in :attr:`ToolResult.data` must be JSON-serializable.
    """

    name: str
    description: str
    parameters_json_schema: dict

    @abstractmethod
    def run(self, inputs: dict) -> ToolResult:
        """Execute the tool with validated ``inputs`` and return a result."""
        raise NotImplementedError  # pragma: no cover


# ---------------------------------------------------------------------------
# JSON Schema -> pydantic model compilation
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _annotation_from_schema(schema: Any, model_name: str) -> Any:
    """Map a JSON Schema fragment onto a Python annotation for pydantic.

    Supports the subset of JSON Schema used by AgentForge tool declarations:
    ``type`` (including lists such as ``["number", "string"]``), ``enum``,
    ``anyOf`` (incl. nullable), ``items`` for arrays and nested ``object``
    schemas with ``properties``/``required``/``additionalProperties``.
    Unrecognized fragments degrade to ``Any`` (validation is a gate for LLM
    inputs, not a security boundary).
    """
    if not isinstance(schema, dict):
        return Any

    if "anyOf" in schema:
        subs = tuple(
            _annotation_from_schema(sub, f"{model_name}_opt{i}")
            for i, sub in enumerate(schema["anyOf"])
        )
        return Union[subs] if subs else Any

    if "enum" in schema:
        values = tuple(schema["enum"])
        if not values:
            return Any
        return Literal[values]  # type: ignore[misc]

    js_type = schema.get("type")
    if isinstance(js_type, list):
        subs = tuple(
            _annotation_from_schema({**schema, "type": t}, model_name)
            for t in js_type
        )
        return Union[subs] if subs else Any

    if js_type == "array":
        items_schema = schema.get("items") or {}
        inner = _annotation_from_schema(items_schema, f"{model_name}_item")
        return list[inner]

    if js_type == "object":
        props = schema.get("properties")
        if not props:
            return dict
        return json_schema_to_pydantic_model(
            f"{model_name}_nested", schema
        )

    if isinstance(js_type, str) and js_type in _JSON_TYPE_MAP:
        return _JSON_TYPE_MAP[js_type]

    return Any


def json_schema_to_pydantic_model(name: str, schema: dict) -> type[pydantic.BaseModel]:
    """Compile a JSON Schema (type ``object``) into a pydantic model class.

    Args:
        name: Name given to the generated model class.
        schema: A JSON Schema dict of type ``object`` with optional
            ``properties``, ``required``, ``additionalProperties``.

    Returns:
        A dynamically created ``pydantic.BaseModel`` subclass. Fields listed
        in ``required`` are mandatory; other fields default to the schema's
        ``default`` (or ``None``). ``additionalProperties: false`` maps to
        ``extra="forbid"`` so unknown keys are rejected.

    Raises:
        ToolInputError: If ``schema`` is not a dict of object type or has no
            usable ``properties`` mapping.
    """
    if not isinstance(schema, dict):
        raise ToolInputError("JSON Schema must be a dict")
    if schema.get("type") not in (None, "object"):
        raise ToolInputError(
            f"top-level JSON Schema must be of type 'object', got {schema.get('type')!r}"
        )
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        raise ToolInputError("JSON Schema must declare a non-empty 'properties' mapping")

    required = set(schema.get("required") or [])
    extra_setting = schema.get("additionalProperties")
    model_config = ConfigDict(
        extra="forbid" if extra_setting is False else "ignore",
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    field_definitions: dict[str, Any] = {}
    for prop_name, prop_schema in props.items():
        prop_schema = prop_schema if isinstance(prop_schema, dict) else {}
        annotation = _annotation_from_schema(prop_schema, f"{name}_{prop_name}")
        description = prop_schema.get("description")

        if prop_name in required:
            field_info = Field(..., description=description, alias=prop_name)
            field_definitions[prop_name] = (annotation, field_info)
        else:
            default = prop_schema.get("default", None)
            if default is None:
                annotation = Optional[annotation]
            field_info = Field(default=default, description=description, alias=prop_name)
            field_definitions[prop_name] = (annotation, field_info)

    model = create_model(
        name,
        __config__=model_config,
        __doc__=(schema.get("description") or f"Validated inputs for {name}"),
        **field_definitions,
    )
    return model


class ToolRegistry:
    """Named registry of :class:`Tool` instances with schema-validated runs.

    Example:
        >>> registry = ToolRegistry()
        >>> registry.register(MyTool())
        >>> result = registry.run("my_tool", {"x": 1})  # never raises
        >>> result.ok
        True
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._validators: dict[str, type[pydantic.BaseModel] | None] = {}

    # -- registration -------------------------------------------------------

    def register(self, tool: Tool, replace: bool = False) -> None:
        """Register ``tool`` under its ``name``.

        Args:
            tool: The tool instance to register.
            replace: Allow silently replacing an existing tool of the same
                name. When False (default) a duplicate name raises.

        Raises:
            ToolInputError: If the tool's ``parameters_json_schema`` cannot be
                compiled into a pydantic validator.
            ValueError: On duplicate registration with ``replace=False``.
        """
        if not isinstance(tool, Tool):
            raise TypeError(f"register() expects a Tool instance, got {type(tool)!r}")
        if not getattr(tool, "name", None):
            raise ValueError("tool must define a non-empty 'name'")
        if tool.name in self._tools and not replace:
            raise ValueError(f"a tool named {tool.name!r} is already registered")

        validator: type[pydantic.BaseModel] | None = None
        schema = getattr(tool, "parameters_json_schema", None)
        if isinstance(schema, dict) and schema.get("properties"):
            try:
                validator = json_schema_to_pydantic_model(
                    f"{tool.name}_inputs", schema
                )
            except ToolInputError:
                logger.warning(
                    "tool %s has an uncompilable parameters_json_schema; "
                    "inputs will only be checked for dict-ness",
                    tool.name,
                )
                validator = None

        self._tools[tool.name] = tool
        self._validators[tool.name] = validator
        logger.debug("registered tool %r", tool.name)

    # -- lookup -------------------------------------------------------------

    def get(self, name: str) -> Tool | None:
        """Return the tool registered under ``name`` or ``None``."""
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        """Return all registered tools in registration order."""
        return list(self._tools.values())

    def names(self) -> list[str]:
        """Return the names of all registered tools in registration order."""
        return list(self._tools.keys())

    def function_calling_specs(self) -> list[dict]:
        """OpenAI-style function-calling specs for every registered tool.

        Useful for wiring the registry straight into an LLM ``tools=`` param.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_json_schema,
                },
            }
            for tool in self._tools.values()
        ]

    # -- execution ----------------------------------------------------------

    def run(self, tool_name: str, inputs: Any) -> ToolResult:
        """Validate ``inputs`` and run the named tool. NEVER raises.

        Args:
            tool_name: Name of a registered tool.
            inputs: Expected to be a dict of tool inputs.

        Returns:
            :class:`ToolResult`. Failure modes captured here: unknown tool,
            non-dict inputs, schema validation failure, and any exception
            escaping the tool implementation.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                ok=False,
                error=f"unknown tool: {tool_name!r} (registered: {self.names()})",
            )

        if inputs is None:
            inputs = {}
        if not isinstance(inputs, dict):
            return ToolResult(
                ok=False,
                error=f"tool {tool_name!r} expects dict inputs, got {type(inputs).__name__}",
            )

        validator = self._validators.get(tool_name)
        if validator is not None:
            try:
                validator.model_validate(inputs)
            except ValidationError as exc:
                return ToolResult(
                    ok=False,
                    error=(
                        f"input validation failed for tool {tool_name!r}: "
                        f"{_format_validation_error(exc)}"
                    ),
                )
            except Exception as exc:  # pragma: no cover - defensive
                return ToolResult(
                    ok=False,
                    error=f"input validation crashed for tool {tool_name!r}: {exc}",
                )

        try:
            return tool.run(inputs)
        except Exception as exc:
            logger.exception("tool %r raised unexpectedly", tool_name)
            return ToolResult(
                ok=False,
                error=f"tool {tool_name!r} raised {type(exc).__name__}: {exc}",
            )


def _format_validation_error(exc: ValidationError) -> str:
    """Render a pydantic ``ValidationError`` as a compact one-line string."""
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        msg = err.get("msg", "invalid")
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts) or str(exc)
