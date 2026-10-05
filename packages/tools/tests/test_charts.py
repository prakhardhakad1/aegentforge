"""Tests for chart rendering (ChartSpec -> PNG) and the ChartTool wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_tools.charts import ChartTool, render_chart_spec, validate_chart_spec

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _bar_spec() -> dict:
    """A minimal valid bar ChartSpec."""
    return {
        "id": "chart_1",
        "kind": "bar",
        "title": "Revenue by region",
        "x_label": "Region",
        "y_label": "Revenue",
        "data": [
            {"label": "north", "x": "north", "y": 120.0},
            {"label": "south", "x": "south", "y": 98.5},
            {"label": "east", "x": "east", "y": 143.2},
        ],
        "notes": "test chart",
    }


class TestValidateChartSpec:
    """validate_chart_spec accepts pinned specs and rejects malformed ones."""

    def test_valid_spec_passes_through(self) -> None:
        """A valid spec is returned unchanged."""
        spec = _bar_spec()
        assert validate_chart_spec(spec) is spec

    def test_rejects_bad_kind(self) -> None:
        """Only bar|line|scatter|pie are allowed."""
        spec = _bar_spec() | {"kind": "histogram"}
        with pytest.raises(ValueError, match="kind"):
            validate_chart_spec(spec)

    def test_rejects_non_dict(self) -> None:
        """Non-dict specs are rejected."""
        with pytest.raises(ValueError, match="dict"):
            validate_chart_spec([1, 2, 3])  # type: ignore[arg-type]

    def test_rejects_empty_data(self) -> None:
        """Empty or missing data lists are rejected."""
        with pytest.raises(ValueError, match="data"):
            validate_chart_spec(_bar_spec() | {"data": []})
        with pytest.raises(ValueError, match="data"):
            validate_chart_spec(_bar_spec() | {"data": "nope"})

    def test_rejects_non_numeric_y(self) -> None:
        """y must be numeric in every point."""
        spec = _bar_spec() | {"data": [{"label": "a", "x": "a", "y": "high"}]}
        with pytest.raises(ValueError, match="numeric"):
            validate_chart_spec(spec)

    def test_bool_y_rejected(self) -> None:
        """Booleans are not numbers for charting purposes."""
        spec = _bar_spec() | {"data": [{"label": "a", "x": "a", "y": True}]}
        with pytest.raises(ValueError, match="numeric"):
            validate_chart_spec(spec)


class TestRenderChartSpec:
    """render_chart_spec produces real, non-empty PNG files for every kind."""

    @pytest.mark.parametrize("kind", ["bar", "line", "scatter", "pie"])
    def test_renders_non_empty_png(self, tmp_path: Path, kind: str) -> None:
        """Each kind renders a file that starts with the PNG magic and is >1 KB."""
        if kind == "line":
            spec = {
                "id": "chart_trend",
                "kind": "line",
                "title": "Revenue over time",
                "x_label": "Week",
                "y_label": "Revenue",
                "data": [{"label": f"w{i}", "x": i, "y": 10 + i * 2} for i in range(10)],
                "notes": "",
            }
        elif kind == "scatter":
            spec = {
                "id": "chart_scatter",
                "kind": "scatter",
                "title": "Units vs revenue",
                "x_label": "units",
                "y_label": "revenue",
                "data": [{"label": "", "x": float(i), "y": float(i) * 1.5} for i in range(30)],
                "notes": "",
            }
        elif kind == "pie":
            spec = {
                "id": "chart_pie",
                "kind": "pie",
                "title": "Churn split",
                "x_label": "",
                "y_label": "Rows",
                "data": [
                    {"label": "no", "x": 0, "y": 80},
                    {"label": "yes", "x": 1, "y": 20},
                ],
                "notes": "",
            }
        else:
            spec = _bar_spec()

        out = render_chart_spec(spec, tmp_path)
        assert out.exists()
        assert out.parent == tmp_path
        blob = out.read_bytes()
        assert blob.startswith(PNG_MAGIC)
        assert len(blob) > 1000, "rendered PNG unexpectedly tiny"

    def test_id_sanitized_into_filename(self, tmp_path: Path) -> None:
        """Weird ids become safe file names."""
        spec = _bar_spec() | {"id": "../../evil chart id!"}
        out = render_chart_spec(spec, tmp_path)
        assert out.parent == tmp_path
        assert out.name == "evil_chart_id.png"

    def test_string_x_for_line_plot(self, tmp_path: Path) -> None:
        """Non-numeric x values plot by position with tick labels."""
        spec = {
            "id": "chart_labels",
            "kind": "line",
            "title": "t",
            "x_label": "date",
            "y_label": "y",
            "data": [
                {"label": "d1", "x": "2026-01-01", "y": 1},
                {"label": "d2", "x": "2026-01-02", "y": 3},
                {"label": "d3", "x": "2026-01-03", "y": 2},
            ],
            "notes": "",
        }
        out = render_chart_spec(spec, tmp_path)
        assert out.read_bytes().startswith(PNG_MAGIC)

    def test_pie_folds_extra_slices(self, tmp_path: Path) -> None:
        """More than 10 pie slices fold the tail into 'other'."""
        spec = {
            "id": "chart_pie_many",
            "kind": "pie",
            "title": "segments",
            "x_label": "",
            "y_label": "rows",
            "data": [{"label": f"s{i}", "x": i, "y": 10 - i} for i in range(14)],
            "notes": "",
        }
        out = render_chart_spec(spec, tmp_path)
        assert out.exists()

    def test_scatter_requires_numeric_x(self, tmp_path: Path) -> None:
        """A scatter with string x values is a ValueError."""
        spec = {
            "id": "bad",
            "kind": "scatter",
            "title": "t",
            "x_label": "x",
            "y_label": "y",
            "data": [{"label": "a", "x": "north", "y": 1}],
            "notes": "",
        }
        with pytest.raises(ValueError, match="numeric x"):
            render_chart_spec(spec, tmp_path)

    def test_pie_requires_positive_y(self, tmp_path: Path) -> None:
        """A pie of only zeros/negatives is a ValueError."""
        spec = {
            "id": "badpie",
            "kind": "pie",
            "title": "t",
            "x_label": "",
            "y_label": "y",
            "data": [{"label": "a", "x": 0, "y": 0}],
            "notes": "",
        }
        with pytest.raises(ValueError, match="positive"):
            render_chart_spec(spec, tmp_path)

    def test_invalid_spec_raises_before_file_write(self, tmp_path: Path) -> None:
        """No file is created for an invalid spec."""
        with pytest.raises(ValueError):
            render_chart_spec({"kind": "banana", "data": []}, tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestChartTool:
    """The Tool wrapper writing into the workspace."""

    def test_renders_into_workspace_charts_dir(self, workspace: Path) -> None:
        """Success writes <workspace>/charts/<id>.png and an artifact dict."""
        tool = ChartTool(workspace)
        result = tool.run({"spec": _bar_spec()})
        assert result.ok is True, result.error
        data = result.data or {}
        chart_path = Path(data["path"])
        assert chart_path == workspace.resolve() / "charts" / "chart_1.png"
        assert chart_path.exists() and chart_path.stat().st_size > 1000
        assert result.artifacts == [
            {"name": "chart_1.png", "path": str(chart_path), "kind": "chart"}
        ]

    def test_invalid_spec_is_ok_false(self, workspace: Path) -> None:
        """Bad specs fail honestly and write nothing."""
        tool = ChartTool(workspace)
        result = tool.run({"spec": {"kind": "banana", "data": [{"y": 1}]}})
        assert result.ok is False
        assert "chart rendering failed" in (result.error or "")
        assert not (workspace / "charts").exists()

    def test_missing_spec(self, workspace: Path) -> None:
        """A missing spec is a rendering failure, not a crash."""
        tool = ChartTool(workspace)
        result = tool.run({})
        assert result.ok is False
