"""Tests for orchestrator.report.render_markdown — GFM rendering."""

from __future__ import annotations

import base64
from pathlib import Path

from orchestrator.report import build_report, render_markdown
from orchestrator.report.models import Report
from orchestrator.report.tests.fixtures import (
    churn_run,
    empty_run,
    unsupported_claims_run,
)

# A 1x1 transparent PNG (smallest valid raster for image-embedding tests).
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class TestSections:
    """The churn report renders every pinned section."""

    def test_title_and_mission(self) -> None:
        md = render_markdown(build_report(churn_run()))
        assert md.startswith("# AgentForge Report:")
        assert "> **Mission:**" in md
        assert "churn spiked in Q3" in md

    def test_all_sections_present(self) -> None:
        md = render_markdown(build_report(churn_run()))
        for heading in (
            "## Executive Summary",
            "## Key Insights",
            "## Charts",
            "## Predictions",
            "## Recommendations",
            "## Appendix",
        ):
            assert heading in md, f"missing section: {heading}"

    def test_strength_badges(self) -> None:
        md = render_markdown(build_report(churn_run()))
        assert "**[HIGH]**" in md

    def test_evidence_lines_rendered(self) -> None:
        md = render_markdown(build_report(churn_run()))
        assert "*Evidence:*" in md
        assert "artifact" in md

    def test_prediction_table_has_confidence_percent(self) -> None:
        md = render_markdown(build_report(churn_run()))
        assert "| # | Prediction | Confidence | Basis |" in md
        assert "78%" in md

    def test_recommendation_table_priority_ordered(self) -> None:
        report = build_report(churn_run())
        md = render_markdown(report)
        assert "| Priority | Recommendation | Action | Expected impact | Effort |" in md
        first_row = md.split("| Priority |")[1].splitlines()[2]
        assert first_row.startswith(f"| 1 |")

    def test_chart_data_table_rendered(self) -> None:
        md = render_markdown(build_report(churn_run()))
        assert "| Label | X | Y |" in md
        assert "Month-to-month" in md

    def test_appendix_included(self) -> None:
        md = render_markdown(build_report(churn_run()))
        assert "### Token usage" in md
        assert "run_churn_001" in md


class TestChartImages:
    """Chart artifact paths become embedded image links when they exist."""

    def test_existing_path_embedded(self, tmp_path: Path) -> None:
        png = tmp_path / "chart_1.png"
        png.write_bytes(_PNG_1X1)
        run = churn_run()
        run["artifacts"][1]["path"] = str(png)
        md = render_markdown(build_report(run))
        assert f"![Churn rate by contract type]({png})" in md

    def test_missing_path_not_embedded(self) -> None:
        run = churn_run()
        run["artifacts"][1]["path"] = "Z:/definitely/not/here/chart.png"
        md = render_markdown(build_report(run))
        assert "![" not in md


class TestStyleOrdering:
    """Section order follows the report's style profile."""

    def test_sales_style_puts_recommendations_before_charts(self) -> None:
        md = render_markdown(build_report(churn_run(), style="sales_insights"))
        assert md.index("## Recommendations") < md.index("## Charts")

    def test_support_style_puts_predictions_before_charts(self) -> None:
        md = render_markdown(build_report(churn_run(), style="support_triage"))
        assert md.index("## Predictions") < md.index("## Charts")

    def test_default_style_puts_charts_before_predictions(self) -> None:
        md = render_markdown(build_report(churn_run(), style="default"))
        assert md.index("## Charts") < md.index("## Predictions")


class TestTolerance:
    """Degenerate reports still render fully."""

    def test_empty_run_renders_honest_placeholders(self) -> None:
        md = render_markdown(build_report(empty_run()))
        assert "No charts were produced" in md
        assert "No predictions were produced" in md
        assert "No recommendations were produced" in md

    def test_unsupported_run_shows_flags(self) -> None:
        md = render_markdown(build_report(unsupported_claims_run()))
        assert "`~absolute_claim`" in md

    def test_minimal_dict_renders(self) -> None:
        md = render_markdown({"title": "Tiny report"})
        assert "# Tiny report" in md
        assert "## Executive Summary" in md

    def test_accepts_report_model(self) -> None:
        md = render_markdown(Report(title="Model report", mission="m"))
        assert "# Model report" in md

    def test_table_pipes_escaped(self) -> None:
        md = render_markdown(
            {
                "title": "Pipes",
                "predictions": [
                    {
                        "claim": "Growth | with pipes",
                        "confidence": 0.5,
                        "basis": "a|b",
                    }
                ],
            }
        )
        assert "Growth \\| with pipes" in md
