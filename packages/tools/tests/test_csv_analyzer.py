"""Tests for CSVAnalyzerTool on committed fixtures and synthetic CSVs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agentforge_tools.csv_analyzer import CSVAnalyzerTool

PINNED_CHART_KINDS = {"bar", "line", "scatter", "pie"}


@pytest.fixture()
def tool(workspace: Path) -> CSVAnalyzerTool:
    """A CSVAnalyzerTool bound to the per-test workspace."""
    return CSVAnalyzerTool(workspace)


def _copy_fixture(workspace: Path, fixtures_dir: Path, name: str) -> str:
    """Copy a committed fixture into the workspace; return its relative path."""
    (workspace / name).write_bytes((fixtures_dir / name).read_bytes())
    return name


def _assert_chart_specs(charts: list) -> None:
    """Every chart list must satisfy the pinned ChartSpec schema."""
    assert 0 < len(charts) <= 6
    for i, spec in enumerate(charts, start=1):
        assert spec["id"] == f"chart_{i}"
        assert spec["kind"] in PINNED_CHART_KINDS
        assert isinstance(spec["title"], str) and spec["title"]
        assert isinstance(spec["data"], list) and spec["data"]
        for point in spec["data"]:
            assert set(point) >= {"label", "x", "y"}
            assert isinstance(point["y"], (int, float)) and not isinstance(point["y"], bool)
        assert isinstance(spec.get("notes", ""), str)


class TestSalesFixture:
    """The rich synthetic sales fixture (dates, regions, churn flag)."""

    def test_full_run(self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path) -> None:
        """All five operations run and produce 3-6 pinned charts."""
        name = _copy_fixture(workspace, fixtures_dir, "sales.csv")
        result = tool.run({"path": name})
        assert result.ok is True, result.error
        data = result.data or {}

        # All operations present.
        for op in ("describe", "correlations", "groupbys", "trends", "segmentation"):
            assert op in data, op

        # Describe: datetime coercion, dtypes, missingness.
        describe = data["describe"]
        assert describe["rows"] > 0
        profiles = {p["name"]: p for p in describe["column_profiles"]}
        assert profiles["date"]["dtype"].startswith("datetime")
        assert "units" in describe["numeric_summary"]

        # Correlations: units and revenue are ~perfectly correlated.
        pairs = data["correlations"]["top_pairs"]
        assert pairs, "expected at least one correlation pair"
        best = max(pairs, key=lambda p: abs(p["correlation"]))
        assert {best["a"], best["b"]} == {"units", "revenue"}

        # Groupbys: low-cardinality region/product detected.
        group_cols = {g["column"] for g in data["groupbys"]["groups"]}
        assert "region" in group_cols

        # Trends: revenue/units trend upward across the date column.
        trends = data["trends"]
        assert trends["sort_basis"] == "date"
        assert trends["top_movers"], "expected top movers"

        # Segmentation: churned flag with yes/no lexicon.
        segmentation = data["segmentation"]
        assert segmentation["flag_column"] == "churned"
        assert segmentation["positive_value"] == "yes"
        assert 0.0 <= segmentation["overall_rate_pct"] <= 100.0
        by_cat = {b["column"] for b in segmentation["by_category"]}
        assert "region" in by_cat

        # Charts: 3-6, pinned schema, on artifacts and mirrored in data.
        charts = data["charts"]
        _assert_chart_specs(charts)
        assert len(charts) >= 3
        assert result.artifacts == charts

        # Everything JSON-serializable (agent envelope requirement).
        json.dumps(result.to_dict())

    def test_churn_question_prioritizes_flag_charts(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """A churn question puts the flag-split charts first."""
        name = _copy_fixture(workspace, fixtures_dir, "sales.csv")
        result = tool.run({"path": name, "question": "Why did churn spike in Q3?"})
        assert result.ok is True
        charts = (result.data or {})["charts"]
        assert charts[0]["kind"] == "pie"
        assert "churned" in charts[0]["title"]

    def test_operations_subset(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """operations=[...] limits which keys land in data."""
        name = _copy_fixture(workspace, fixtures_dir, "sales.csv")
        result = tool.run({"path": name, "operations": ["describe"]})
        assert result.ok is True
        data = result.data or {}
        assert "describe" in data
        assert "correlations" not in data
        assert "trends" not in data


class TestEdgeFixtures:
    """messy.csv (missing values), header_only.csv, empty.csv, dates.csv."""

    def test_messy_missing_values(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """NaN cells are tolerated and surfaced by the missing-values chart."""
        name = _copy_fixture(workspace, fixtures_dir, "messy.csv")
        result = tool.run({"path": name})
        assert result.ok is True, result.error
        data = result.data or {}

        describe = data["describe"]
        profiles = {p["name"]: p for p in describe["column_profiles"]}
        assert profiles["spend"]["missing"] == 2
        assert profiles["conversions"]["missing"] == 1
        assert profiles["channel"]["missing"] == 1

        chart_titles = {c["title"] for c in data["charts"]}
        assert "Missing values by column" in chart_titles  # missing chart present
        assert data["charts"], "messy.csv should still produce charts"

    def test_header_only_csv(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """Headers but no rows: ok=True with an explicit note, no crash."""
        name = _copy_fixture(workspace, fixtures_dir, "header_only.csv")
        result = tool.run({"path": name})
        assert result.ok is True, result.error
        data = result.data or {}
        assert data["summary"]["rows"] == 0
        assert "file contains headers but no data rows" in data["summary"]["notes"]

    def test_empty_csv_fails_honestly(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """A zero-byte file is an error, not fake success."""
        name = _copy_fixture(workspace, fixtures_dir, "empty.csv")
        result = tool.run({"path": name})
        assert result.ok is False
        assert "empty" in (result.error or "").lower()

    def test_dates_fixture_trend(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """A clean date-numeric file yields an upward trend chart over dates."""
        name = _copy_fixture(workspace, fixtures_dir, "dates.csv")
        result = tool.run({"path": name, "operations": ["describe", "trends"]})
        assert result.ok is True, result.error
        data = result.data or {}
        trends = data["trends"]
        assert trends["sort_basis"] == "date"
        visits = next(t for t in trends["trends"] if t["column"] == "visits")
        assert visits["direction"] == "up"
        chart = data["charts"][0]
        assert chart["kind"] == "line"
        assert chart["x_label"] == "date"

    def test_datetime_coercion_note(
        self, tool: CSVAnalyzerTool, workspace: Path, fixtures_dir: Path
    ) -> None:
        """String date columns are coerced with an explicit note."""
        name = _copy_fixture(workspace, fixtures_dir, "dates.csv")
        result = tool.run({"path": name})
        assert result.ok is True
        notes = (result.data or {})["summary"]["notes"]
        assert any("datetime" in n for n in notes)


class TestSyntheticCsvs:
    """Generated-in-test datasets: row cap, all-categorical, non-CSV garbage."""

    def test_oversized_file_row_cap(self, workspace: Path) -> None:
        """A file over the size cap is truncated to CSV_ROW_CAP rows with a note."""
        rng = np.random.default_rng(42)
        rows = 40_000
        df = pd.DataFrame(
            {
                "id": np.arange(rows),
                "value": rng.normal(size=rows),
                "score": rng.uniform(0, 100, size=rows),
                "group": rng.choice(["a", "b", "c"], size=rows),
            }
        )
        path = workspace / "big.csv"
        df.to_csv(path, index=False)
        assert path.stat().st_size > 1_000_000  # over the 1 MB cap below

        tool = CSVAnalyzerTool(workspace, max_file_mb=1, row_cap=500)
        result = tool.run({"path": "big.csv"})
        assert result.ok is True, result.error
        data = result.data or {}
        assert data["summary"]["rows"] == 500
        assert any("CSV_MAX_FILE_MB" in n and "500" in n for n in data["summary"]["notes"])

    def test_all_categorical_columns(
        self, tool: CSVAnalyzerTool, workspace: Path
    ) -> None:
        """A CSV with no numeric columns degrades gracefully."""
        (workspace / "cats.csv").write_text(
            "name,color\nalice,red\nbob,blue\ncarol,red\n", encoding="utf-8"
        )
        result = tool.run({"path": "cats.csv"})
        assert result.ok is True, result.error
        data = result.data or {}
        assert "no numeric columns" in data["groupbys"]["note"]
        assert data["describe"]["numeric_summary"] == {}

    def test_broken_csv_fails_cleanly(self, tool: CSVAnalyzerTool, workspace: Path) -> None:
        """Structurally broken CSVs (unterminated quote) fail with a parse error."""
        (workspace / "broken.csv").write_text(
            'a,b\n"1,2\n3,4\n', encoding="utf-8"
        )
        result = tool.run({"path": "broken.csv"})
        assert result.ok is False
        assert "parse" in (result.error or "").lower()

    def test_binary_junk_degrades_to_single_column(
        self, tool: CSVAnalyzerTool, workspace: Path
    ) -> None:
        """Binary junk with no delimiters parses as a 1-column CSV (honest read).

        pandas' ``encoding_errors="replace"`` means arbitrary bytes never
        crash the tool; the summary simply reflects what could be decoded.
        """
        (workspace / "junk.csv").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 64)
        result = tool.run({"path": "junk.csv"})
        assert result.ok is True
        data = result.data or {}
        assert data["summary"]["columns"] == 1
        json.dumps(result.to_dict())


class TestCSVAnalyzerInputValidation:
    """Path policy and operations validation."""

    def test_missing_path(self, tool: CSVAnalyzerTool) -> None:
        """path is required."""
        assert tool.run({}).ok is False
        assert tool.run({"path": "  "}).ok is False

    def test_nonexistent_file(self, tool: CSVAnalyzerTool) -> None:
        """A missing file fails with file-not-found."""
        result = tool.run({"path": "nope.csv"})
        assert result.ok is False and "not found" in (result.error or "")

    def test_traversal_rejected(self, tool: CSVAnalyzerTool, tmp_path: Path) -> None:
        """csv_analyzer is workspace-scoped: ../ escapes are rejected."""
        secret = tmp_path / "secret.csv"
        secret.write_text("a,b\n1,2\n", encoding="utf-8")
        result = tool.run({"path": "../secret.csv"})
        assert result.ok is False
        assert "rejected" in (result.error or "")

    def test_directory_path_rejected(self, tool: CSVAnalyzerTool, workspace: Path) -> None:
        """A directory cannot be analyzed."""
        (workspace / "subdir").mkdir()
        result = tool.run({"path": "subdir"})
        assert result.ok is False and "directory" in (result.error or "")

    def test_unknown_operation(self, tool: CSVAnalyzerTool, workspace: Path) -> None:
        """Unknown operation names are listed back in the error."""
        (workspace / "f.csv").write_text("a\n1\n2\n", encoding="utf-8")
        result = tool.run({"path": "f.csv", "operations": ["describe", "fly"]})
        assert result.ok is False
        assert "fly" in (result.error or "")

    def test_empty_operations(self, tool: CSVAnalyzerTool, workspace: Path) -> None:
        """An empty operations list is rejected."""
        (workspace / "f.csv").write_text("a\n1\n2\n", encoding="utf-8")
        assert tool.run({"path": "f.csv", "operations": []}).ok is False

    def test_non_list_operations(self, tool: CSVAnalyzerTool, workspace: Path) -> None:
        """A non-list operations value is rejected."""
        (workspace / "f.csv").write_text("a\n1\n2\n", encoding="utf-8")
        assert tool.run({"path": "f.csv", "operations": "describe"}).ok is False

    def test_non_string_question(self, tool: CSVAnalyzerTool, workspace: Path) -> None:
        """A non-string question is rejected."""
        (workspace / "f.csv").write_text("a\n1\n2\n", encoding="utf-8")
        assert tool.run({"path": "f.csv", "question": 7}).ok is False
