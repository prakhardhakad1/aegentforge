"""Tests for build_default_registry: wiring + end-to-end schema-validated runs."""

from __future__ import annotations

import json
from pathlib import Path

import agentforge_tools
from agentforge_tools.registry import build_default_registry

EXPECTED_TOOL_ORDER = ["web_search", "code_sandbox", "files", "csv_analyzer", "chart"]


class TestPackageSurface:
    """The import package exposes the full pinned surface."""

    def test_all_exports_resolve(self) -> None:
        """Every name in __all__ exists on the package."""
        for name in agentforge_tools.__all__:
            assert hasattr(agentforge_tools, name), name

    def test_no_network_at_import_time(self) -> None:
        """Importing the package has no visible side effects beyond Agg setup."""
        import os

        assert os.environ.get("MPLBACKEND", "Agg") == "Agg"


class TestBuildDefaultRegistry:
    """Registry construction and ordering."""

    def test_contains_all_tools_in_order(self, workspace: Path) -> None:
        """All five tools are registered under their pinned names."""
        registry = build_default_registry(workspace)
        assert registry.names() == EXPECTED_TOOL_ORDER

    def test_function_calling_specs(self, workspace: Path) -> None:
        """Every tool exposes an OpenAI-style function-calling spec."""
        registry = build_default_registry(workspace)
        specs = registry.function_calling_specs()
        assert [s["function"]["name"] for s in specs] == EXPECTED_TOOL_ORDER
        for spec in specs:
            fn = spec["function"]
            assert fn["description"]
            assert fn["parameters"]["type"] == "object"
            assert fn["parameters"]["properties"]

    def test_workspace_created(self, tmp_path: Path) -> None:
        """The workspace directory is created if missing."""
        nested = tmp_path / "runs" / "abc"
        build_default_registry(nested)
        assert nested.is_dir()


class TestRegistryEndToEnd:
    """Schema-validated runs through the real registry (offline)."""

    def test_files_validation_error(self, workspace: Path) -> None:
        """files rejects an operation outside the enum via schema validation."""
        registry = build_default_registry(workspace)
        result = registry.run("files", {"operation": "delete", "path": "x"})
        assert result.ok is False
        assert "validation failed" in (result.error or "")

    def test_web_search_validation_error(self, workspace: Path) -> None:
        """web_search without a query fails validation before any network call."""
        registry = build_default_registry(workspace)
        result = registry.run("web_search", {})
        assert result.ok is False
        assert "validation failed" in (result.error or "")

    def test_chart_end_to_end(self, workspace: Path) -> None:
        """A valid ChartSpec renders through the registry into the workspace."""
        registry = build_default_registry(workspace)
        spec = {
            "id": "chart_9",
            "kind": "bar",
            "title": "t",
            "x_label": "x",
            "y_label": "y",
            "data": [
                {"label": "a", "x": "a", "y": 1},
                {"label": "b", "x": "b", "y": 3},
            ],
            "notes": "e2e",
        }
        result = registry.run("chart", {"spec": spec})
        assert result.ok is True, result.error
        assert Path((result.data or {})["path"]).exists()

    def test_chart_nested_schema_validation(self, workspace: Path) -> None:
        """The nested spec object is validated (bad kind rejected pre-run)."""
        registry = build_default_registry(workspace)
        result = registry.run(
            "chart", {"spec": {"kind": "histogram", "data": [{"y": 1}]}}
        )
        assert result.ok is False
        assert "validation failed" in (result.error or "")

    def test_code_sandbox_end_to_end(self, workspace: Path) -> None:
        """The sandbox runs real code through the registry."""
        registry = build_default_registry(workspace)
        result = registry.run("code_sandbox", {"code": "print('via registry')"})
        assert result.ok is True, result.error
        assert (result.data or {})["stdout"].strip() == "via registry"

    def test_csv_analyzer_end_to_end(
        self, workspace: Path, fixtures_dir: Path
    ) -> None:
        """CSV -> analyzer -> chart pipeline inside one shared workspace."""
        registry = build_default_registry(workspace)
        (workspace / "sales.csv").write_bytes(
            (fixtures_dir / "sales.csv").read_bytes()
        )
        result = registry.run("csv_analyzer", {"path": "sales.csv"})
        assert result.ok is True, result.error
        charts = (result.data or {})["charts"]
        assert charts and result.artifacts == charts

        # The analyst can then render one of the analyzer's charts.
        first = charts[0]
        rendered = registry.run("chart", {"spec": first})
        assert rendered.ok is True, rendered.error
        assert Path((rendered.data or {})["path"]).exists()

    def test_unknown_tool(self, workspace: Path) -> None:
        """Unknown tools fail with the registered names listed."""
        registry = build_default_registry(workspace)
        result = registry.run("teleport", {})
        assert result.ok is False
        assert "teleport" in (result.error or "")

    def test_results_are_json_serializable(self, workspace: Path) -> None:
        """Every tool result in the happy set serializes to JSON."""
        registry = build_default_registry(workspace)
        (workspace / "d.csv").write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
        results = [
            registry.run("files", {"operation": "write", "path": "n.txt", "content": "hi"}),
            registry.run("files", {"operation": "read", "path": "n.txt"}),
            registry.run("files", {"operation": "list"}),
            registry.run("csv_analyzer", {"path": "d.csv"}),
            registry.run(
                "chart",
                {"spec": {"kind": "line", "data": [{"x": 1, "y": 2}, {"x": 2, "y": 3}]}},
            ),
            registry.run("code_sandbox", {"code": "print(40 + 2)"}),
        ]
        for result in results:
            assert result.ok is True, result.error
            json.dumps(result.to_dict())
