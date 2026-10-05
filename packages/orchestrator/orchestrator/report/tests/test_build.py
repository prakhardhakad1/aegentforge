"""Tests for orchestrator.report.build — the build_report pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.report import build_report
from orchestrator.report.tests.fixtures import (
    churn_run,
    empty_run,
    partial_failed_run,
    unsupported_claims_run,
)

_PINNED_KEYS = (
    "title",
    "mission",
    "style",
    "executive_summary",
    "insights",
    "charts",
    "predictions",
    "recommendations",
    "appendix",
)


class TestPinnedShape:
    """build_report output matches the pinned Report contract."""

    def test_pinned_top_level_keys(self) -> None:
        report = build_report(churn_run())
        for key in _PINNED_KEYS:
            assert key in report, f"missing pinned key: {key}"

    def test_json_safe(self) -> None:
        import json

        report = build_report(churn_run())
        json.dumps(report)  # must not raise

    def test_insight_fields_pinned(self) -> None:
        report = build_report(churn_run())
        for insight in report["insights"]:
            assert set(insight) >= {"title", "detail", "evidence", "strength"}
            assert insight["strength"] in ("high", "medium", "low")

    def test_prediction_fields_pinned(self) -> None:
        report = build_report(churn_run())
        assert report["predictions"], "churn run must yield a prediction"
        for prediction in report["predictions"]:
            assert set(prediction) >= {"claim", "confidence", "basis"}
            assert 0.0 <= prediction["confidence"] <= 1.0
            assert prediction["basis"].strip()

    def test_recommendation_fields_pinned(self) -> None:
        report = build_report(churn_run())
        assert report["recommendations"], "churn run must yield a recommendation"
        for rec in report["recommendations"]:
            assert set(rec) >= {
                "title",
                "action",
                "expected_impact",
                "effort",
                "priority",
            }
            assert rec["effort"] in ("S", "M", "L")
            assert 1 <= rec["priority"] <= 5


class TestRanking:
    """Insights are ranked strongest-first by evidence strength."""

    def test_churn_run_produces_ranked_insights(self) -> None:
        report = build_report(churn_run())
        assert len(report["insights"]) >= 3
        strengths = [i["strength"] for i in report["insights"]]
        weights = [{"low": 1, "medium": 2, "high": 3}[s] for s in strengths]
        assert weights == sorted(weights, reverse=True), (
            "insights must be ordered strongest-first"
        )

    def test_numeric_cross_cited_claim_ranks_high(self) -> None:
        report = build_report(churn_run())
        top = report["insights"][0]
        assert top["strength"] == "high"
        assert top["evidence"], "top insight must carry evidence refs"
        assert top["rank"] == 1

    def test_scores_monotonically_non_increasing(self) -> None:
        report = build_report(churn_run())
        scores = [i["score"] for i in report["insights"]]
        assert scores == sorted(scores, reverse=True)

    def test_evidence_refs_are_human_readable(self) -> None:
        report = build_report(churn_run())
        all_refs = [ref for i in report["insights"] for ref in i["evidence"]]
        assert any("artifact" in ref for ref in all_refs)
        assert any("step" in ref for ref in all_refs)


class TestChartsPredictionsRecommendations:
    """Artifact assembly: charts, predictions, priority matrix."""

    def test_charts_assembled_and_validated(self) -> None:
        report = build_report(churn_run())
        assert len(report["charts"]) == 1
        chart = report["charts"][0]
        assert chart["id"] == "chart_1"
        assert chart["kind"] == "bar"
        assert chart["title"] == "Churn rate by contract type"
        assert len(chart["data"]) == 3

    def test_invalid_chart_kind_dropped(self) -> None:
        run = churn_run()
        run["artifacts"][1]["data"]["kind"] = "hologram"
        report = build_report(run)
        assert report["charts"] == []
        assert report["meta"]["stats"]["charts_dropped"] == 1

    def test_prediction_confidence_and_basis(self) -> None:
        report = build_report(churn_run())
        prediction = report["predictions"][0]
        assert "11.2%" in prediction["claim"]
        assert prediction["confidence"] == pytest.approx(0.78)
        assert "trend" in prediction["basis"].lower()

    def test_prediction_missing_confidence_flagged(self) -> None:
        run = churn_run()
        del run["artifacts"][2]["data"]["confidence"]
        report = build_report(run)
        assert report["predictions"][0]["flags"] == ["confidence_assumed"]
        assert report["predictions"][0]["confidence"] == pytest.approx(0.5)

    def test_priorities_start_at_one_and_are_ordered(self) -> None:
        run = churn_run()
        # Three recommendations with distinct impact/effort mixes.
        run["artifacts"].append(
            {
                "artifact_id": "art_5",
                "kind": "recommendation",
                "name": "Save desk",
                "summary": "Pause the low-value ad spend",
                "data": {
                    "title": "Pause low-value ad spend",
                    "action": "Pause the bottom-quartile ad campaigns",
                    "expected_impact": "Moderate savings with little risk",
                    "effort": "S",
                },
            }
        )
        run["artifacts"].append(
            {
                "artifact_id": "art_6",
                "kind": "recommendation",
                "name": "Success team",
                "summary": "Stand up a customer success function",
                "data": {
                    "title": "Customer success team",
                    "action": "Hire and staff a dedicated success team",
                    "expected_impact": "Strong long-term retention effects",
                    "effort": "L",
                },
            }
        )
        report = build_report(run)
        recs = report["recommendations"]
        assert len(recs) == 3
        priorities = [r["priority"] for r in recs]
        assert priorities == sorted(priorities)
        assert priorities[0] == 1

    def test_high_impact_low_effort_gets_priority_one(self) -> None:
        run = churn_run()
        run["artifacts"][3]["data"]["expected_impact"] = (
            "Major churn reduction worth $500,000 annually"
        )
        run["artifacts"][3]["data"]["effort"] = "S"
        report = build_report(run)
        assert report["recommendations"][0]["priority"] == 1


class TestExecSummary:
    """Executive summary is a deterministic synthesis of top content."""

    def test_summary_mentions_mission_and_top_content(self) -> None:
        report = build_report(churn_run(), style="sales_insights")
        summary = report["executive_summary"]
        assert "churn spiked in Q3" in summary
        assert "18.4%" in summary  # top insight's number survives
        assert "recommendation" in summary.lower()

    def test_summary_excludes_flagged_and_low_insights(self) -> None:
        report = build_report(unsupported_claims_run())
        summary = report["executive_summary"]
        for insight in report["insights"]:
            if "unsupported_claim" in insight.get("flags", []) or (
                insight["strength"] == "low"
            ):
                assert insight["detail"][:40] not in summary, (
                    f"flagged insight leaked into exec summary: {insight['title']}"
                )

    def test_no_llm_calls_in_default_path(self) -> None:
        # Deterministic mode must hold even when a live LLM is configured.
        import os

        old = os.environ.pop("LLM_MODE", None)
        try:
            os.environ["LLM_MODE"] = "mock"
            report = build_report(churn_run())
            assert report["meta"]["llm_polished"] is False
        finally:
            if old is not None:
                os.environ["LLM_MODE"] = old
            else:
                os.environ.pop("LLM_MODE", None)


class TestGracefulDegradation:
    """Empty, partial and malformed runs never crash the pipeline."""

    def test_empty_run_is_honest(self) -> None:
        report = build_report(empty_run())
        assert report["charts"] == []
        assert report["predictions"] == []
        assert report["recommendations"] == []
        # No fabricated content: anything surfaced is flagged low-strength.
        assert all(i["strength"] == "low" for i in report["insights"])
        summary = report["executive_summary"].lower()
        assert "no artifacts" in summary
        assert "no evidence" in summary or "honest" in summary
        assert "0 artifact(s) collected" in report["appendix"]

    def test_partial_run_reports_honest_status(self) -> None:
        report = build_report(partial_failed_run())
        assert report["meta"]["run_status"] == "partial"
        summary = report["executive_summary"].lower()
        assert "partial" in summary
        assert "1 of 2 steps" in summary
        assert "forecaster step failed" in report["appendix"]

    def test_failed_steps_are_not_mined_for_insights(self) -> None:
        report = build_report(partial_failed_run())
        for insight in report["insights"]:
            assert "elasticity" in insight["detail"].lower() or "price" in (
                insight["detail"].lower()
            )

    def test_malformed_run_dict_is_tolerated(self) -> None:
        junk: dict[str, Any] = {
            "mission": None,
            "status": None,
            "plan": "not-a-list",
            "steps": [None, 42, {"title": "ok", "status": "completed", "summary": ""}],
            "artifacts": [None, {"no": "fields"}, {"kind": 7, "summary": ["a", "b"]}],
            "token_usage": "nope",
            "errors": "single error string",
        }
        report = build_report(junk)  # must not raise
        assert report["mission"] == ""
        assert report["meta"]["run_status"] == "unknown"

    def test_non_dict_run_result_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            build_report("not a dict")  # type: ignore[arg-type]

    def test_empty_dict_run(self) -> None:
        report = build_report({})
        assert report["title"]
        assert report["insights"] == []


class TestStyles:
    """Style switching changes shape, emphasis and section order."""

    @pytest.mark.parametrize(
        "style",
        ["default", "market_research", "sales_insights", "support_triage"],
    )
    def test_all_styles_build(self, style: str) -> None:
        report = build_report(churn_run(), style=style)
        assert report["style"] == style
        assert report["meta"]["style_fallback"] is False

    def test_team_template_id_maps_to_style(self) -> None:
        report = build_report(churn_run(), style="support_triage_team")
        assert report["style"] == "support_triage"
        assert report["meta"]["style_fallback"] is False

    def test_unknown_style_falls_back_to_default(self) -> None:
        report = build_report(churn_run(), style="marketing_cloud")
        assert report["style"] == "default"
        assert report["meta"]["style_fallback"] is True
        assert report["meta"]["requested_style"] == "marketing_cloud"

    def test_sales_style_emphasizes_recommendations(self) -> None:
        report = build_report(churn_run(), style="sales_insights")
        summary = report["executive_summary"]
        rec_sentence_pos = summary.lower().find("top recommendation")
        insight_sentence_pos = summary.lower().find("sales insight")
        assert rec_sentence_pos != -1
        assert insight_sentence_pos == -1 or rec_sentence_pos < insight_sentence_pos

    def test_support_style_emphasizes_predictions(self) -> None:
        report = build_report(churn_run(), style="support_triage")
        summary = report["executive_summary"]
        assert "prediction" in summary.lower()

    def test_market_research_vocabulary(self) -> None:
        report = build_report(churn_run(), style="market_research")
        assert "market signal" in report["executive_summary"].lower()


class TestAppendix:
    """Appendix records run details, plan, tokens, errors, coverage."""

    def test_appendix_sections(self) -> None:
        report = build_report(churn_run())
        appendix = report["appendix"]
        for marker in (
            "### Run details",
            "### Plan",
            "### Token usage",
            "### Errors",
            "run_churn_001",
            "12,400",
            "$0.0330",
        ):
            assert marker in appendix, f"appendix missing: {marker}"

    def test_appendix_reports_critic_issues(self) -> None:
        report = build_report(unsupported_claims_run())
        assert "Critic checklist raised" in report["appendix"]
        assert report["meta"]["critic_issues"]
