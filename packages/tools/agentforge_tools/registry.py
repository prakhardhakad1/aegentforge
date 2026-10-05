"""Default tool registry wiring all AgentForge tools to a shared workspace."""

from __future__ import annotations

from pathlib import Path

from agentforge_tools.base import ToolRegistry
from agentforge_tools.charts import ChartTool
from agentforge_tools.csv_analyzer import CSVAnalyzerTool
from agentforge_tools.files import FileTools
from agentforge_tools.sandbox import CodeSandboxTool
from agentforge_tools.web_search import WebSearchTool

__all__ = ["build_default_registry"]


def build_default_registry(workspace_dir: str | Path) -> ToolRegistry:
    """Create a :class:`ToolRegistry` with all built-in tools.

    Tools sharing ``workspace_dir`` (files, csv_analyzer, chart, and the
    sandbox's artifact copy-out) operate on one run workspace so an analyst
    agent can write a CSV, analyze it, and render charts into the same tree.

    Args:
        workspace_dir: Run workspace root; created (recursively) if missing.

    Returns:
        Registry containing (in order): ``web_search``, ``code_sandbox``,
        ``files``, ``csv_analyzer``, ``chart``.
    """
    workspace = Path(workspace_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    registry = ToolRegistry()
    registry.register(WebSearchTool())
    registry.register(CodeSandboxTool(workspace_dir=workspace))
    registry.register(FileTools(workspace))
    registry.register(CSVAnalyzerTool(workspace))
    registry.register(ChartTool(workspace))
    return registry
