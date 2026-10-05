"""Tests for orchestrator.report.export_pdf — fpdf2 PDF export.

Includes the regression test for the reported integration bug: PDF export
crashed on table-heavy reports with a ``_write_table`` type error.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from orchestrator.report import build_report, export_pdf, render_markdown
from orchestrator.report.tests.fixtures import churn_run, empty_run

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _assert_valid_pdf(path: Path, min_bytes: int = 1024) -> None:
    """Basic PDF sanity: magic header and a size floor."""
    data = path.read_bytes()
    assert data.startswith(b"%PDF-"), f"not a PDF: {data[:10]!r}"
    assert len(data) >= min_bytes, f"PDF suspiciously small: {len(data)} bytes"
    assert b"%%EOF" in data[-64:], "PDF missing EOF marker"


class TestExportFromReport:
    """Report dicts / models export to valid PDF bytes."""

    def test_churn_report_pdf(self, tmp_path: Path) -> None:
        out = export_pdf(build_report(churn_run()), tmp_path / "report.pdf")
        assert out == tmp_path / "report.pdf"
        _assert_valid_pdf(out)

    def test_report_model_source(self, tmp_path: Path) -> None:
        report = build_report(churn_run())
        from orchestrator.report.models import Report

        model = Report.model_validate(report)
        out = export_pdf(model, tmp_path / "model.pdf")
        _assert_valid_pdf(out)

    def test_parent_dirs_created(self, tmp_path: Path) -> None:
        out = export_pdf(build_report(churn_run()), tmp_path / "a" / "b" / "r.pdf")
        _assert_valid_pdf(out)

    def test_empty_report_still_exports(self, tmp_path: Path) -> None:
        out = export_pdf(build_report(empty_run()), tmp_path / "empty.pdf")
        _assert_valid_pdf(out, min_bytes=256)

    def test_chart_image_embedded(self, tmp_path: Path) -> None:
        png = tmp_path / "chart_1.png"
        png.write_bytes(_PNG_1X1)
        run = churn_run()
        run["artifacts"][1]["path"] = str(png)
        out = export_pdf(build_report(run), tmp_path / "with_image.pdf")
        _assert_valid_pdf(out)


class TestExportFromMarkdown:
    """Markdown strings export directly (the backend's markdown path)."""

    def test_markdown_string(self, tmp_path: Path) -> None:
        md = render_markdown(build_report(churn_run()))
        out = export_pdf(md, tmp_path / "from_md.pdf")
        _assert_valid_pdf(out)

    def test_empty_markdown(self, tmp_path: Path) -> None:
        out = export_pdf("", tmp_path / "blank.pdf")
        _assert_valid_pdf(out, min_bytes=256)

    def test_unicode_and_emoji_do_not_crash(self, tmp_path: Path) -> None:
        md = (
            "# Report — with unicode\n\n"
            "Curly quotes “here”, em—dashes, € signs, → arrows and 🎉 emoji.\n"
        )
        out = export_pdf(md, tmp_path / "unicode.pdf")
        _assert_valid_pdf(out, min_bytes=256)


class TestTableHeavyRegression:
    """Regression for the reported bug: _write_table crash on table-heavy reports.

    The HTML parser used to hand ``headers`` to fpdf2 as a list of ROWS
    (list-of-lists), raising ``AttributeError: 'list' object has no attribute
    'strip'`` inside the fpdf2 col-width path — and the fallback then raised
    ``TypeError`` joining lists. Both paths must now be bulletproof.
    """

    TABLE_HEAVY_MARKDOWN = """# Stress report

> **Mission:** survive hostile tables

## Executive Summary

Deterministic prose before the tables.

## Predictions

| # | Prediction | Confidence | Basis |
|---|---|---|---|
| 1 | A prediction with unicode –—’“ and emoji 🎉 | 82% | basis with a-really-long-unbroken-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |
| 2 | Row with |an embedded| pipe | 99% | short basis |
| 3 | Sparse | | | |

## Recommendations

| Priority | Recommendation | Action | Expected impact | Effort |
|---|---|---|---|---|
| 1 | Do it | do the thing now | high impact | S |
| 2 | Also this | another action | moderate | M |

## Charts

| Label | X | Y |
|---|---|---|
| Month-to-month | 1 | 18.4 |
| Annual | 2 | 4.1 |

## Wide table (7 columns, no width hints)

| A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| ragged | row | | | | | |
"""

    @pytest.mark.parametrize("source_kind", ["markdown", "report"])
    def test_table_heavy_export(self, tmp_path: Path, source_kind: str) -> None:
        if source_kind == "markdown":
            source: object = self.TABLE_HEAVY_MARKDOWN
        else:
            source = build_report(churn_run())  # real tables, real content
        out = export_pdf(source, tmp_path / f"tables_{source_kind}.pdf")
        _assert_valid_pdf(out)

    def test_ragged_and_hostile_cells(self, tmp_path: Path) -> None:
        md = (
            "# Ragged\n\n"
            "| H1 | H2 |\n"
            "|---|---|\n"
            "| one |\n"           # short row
            "| a | b | c | d |\n"  # long row
            "| 99% | $1,200 |\n"   # numerics
        )
        out = export_pdf(md, tmp_path / "ragged.pdf")
        _assert_valid_pdf(out, min_bytes=256)

    def test_multipage_report(self, tmp_path: Path) -> None:
        md = "# Long report\n\n" + "\n\n".join(
            f"## Section {i}\n\n" + ("Lorem ipsum dolor sit amet. " * 40)
            for i in range(1, 13)
        )
        out = export_pdf(md, tmp_path / "long.pdf")
        _assert_valid_pdf(out, min_bytes=2048)


class TestInputValidation:
    """export_pdf rejects unusable sources with a clear error."""

    def test_invalid_source_type_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            export_pdf(12345, tmp_path / "bad.pdf")  # type: ignore[arg-type]

    def test_returns_resolved_path(self, tmp_path: Path) -> None:
        out = export_pdf("# T\n\nHello.", tmp_path / "p.pdf")
        assert isinstance(out, Path)
        assert out.is_absolute() or str(out) == str(tmp_path / "p.pdf")
