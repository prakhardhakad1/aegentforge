"""agentforge_tools: the AgentForge agent tool layer (packages/tools).

Pinned contracts live in :mod:`agentforge_tools.base` (:class:`Tool`,
:class:`ToolResult`, :class:`ToolRegistry`). High-level wiring:
:func:`build_default_registry`.
"""

from agentforge_tools.base import (
    Tool,
    ToolInputError,
    ToolRegistry,
    ToolResult,
    json_schema_to_pydantic_model,
)
from agentforge_tools.charts import ChartTool, render_chart_spec
from agentforge_tools.csv_analyzer import CSVAnalyzerTool
from agentforge_tools.files import FileTools, PathPolicyError, resolve_in_workspace
from agentforge_tools.registry import build_default_registry
from agentforge_tools.sandbox import CodeSandboxTool
from agentforge_tools.web_search import (
    BraveSearchProvider,
    DuckDuckGoProvider,
    SearchResult,
    WebSearchProvider,
    WebSearchTool,
)

__version__ = "0.1.0"

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "ToolInputError",
    "json_schema_to_pydantic_model",
    "WebSearchTool",
    "WebSearchProvider",
    "SearchResult",
    "DuckDuckGoProvider",
    "BraveSearchProvider",
    "CodeSandboxTool",
    "FileTools",
    "PathPolicyError",
    "resolve_in_workspace",
    "CSVAnalyzerTool",
    "ChartTool",
    "render_chart_spec",
    "build_default_registry",
    "__version__",
]
