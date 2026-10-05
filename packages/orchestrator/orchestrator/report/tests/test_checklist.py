"""Tests for orchestrator.report.critic_checklist — unsupported-claim rejection."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.report import build_report, run_critic_checklist
from orchestrator.report.models import Report
from orchestrator.report.tests.fixtures import churn_run, unsupported_claims_run


def _weak_report_dict() -> dict[str, Any]:
    """A hand-built report full of checklist violations."""
    return {
        "title": "Weak report",
        "mission": "m",
        "style": "default",
        "executive_summary": "",
        "insights": [
            {
                "title": "Unsupported claim",
                "detail": "Something seems generally okay-ish in the workflow overall",
                "evidence": [],
                "strength": "high",
            },
            {
                "title": "Overclaim",
                "detail": "A claim without any numbers in it",
                "evidence": ["text artifact 'x'"],
                "strength": "high",
            },
            {
                "title": "Absolute claim",
                "detail": "This will always work and is guaranteed to succeed for everyone",
                "evidence": [],
                "strength": "medium",
            },
        ],
        "charts": [
            {"id": "chart_empty", "kind": "bar", "title": "Empty", "data": []},
            {
                "id": "chart_ok",
                "kind": "line",
                "title": "Ok",
                "data": [{"label": "a", "x": 1, "y": 2}],
            },
        ],
        "predictions": [
            {"claim": "Confident prediction", "confidence": 0.9, "basis": ""},
            {"claim": "Mystery prediction"},
        ],
        "recommendations": [
            {"title": "Do the thing", "action": "", "expected_impact": "", "priority": 2}
        ],
        "appendix": "",
    }


class TestRejectionRules:
    """R1-R7: unsupported claims are downgraded, flagged and reported."""

    def test_r1_unsupported_claim_downgraded_and_flagged(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        target = next(i for i in report.insights if i.title == "Unsupported claim")
        assert target.strength.value == "low"
        assert "unsupported_claim" in target.flags
        assert any("unsupported_claim" in issue for issue in issues)

    def test_r2_overclaim_downgraded_to_medium(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        target = next(i for i in report.insights if i.title == "Overclaim")
        assert target.strength.value == "medium"
        assert "overclaim" in target.flags
        assert any("overclaim" in issue for issue in issues)

    def test_r3_absolute_claim_flagged(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        target = next(i for i in report.insights if i.title == "Absolute claim")
        assert "absolute_claim" in target.flags
        assert target.strength.value == "low"
        assert any("absolute_claim" in issue for issue in issues)

    def test_r4_prediction_basis_patched(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        for prediction in report.predictions:
            assert prediction.basis.strip(), "basis must exist after checking"
        assert any("missing_prediction_basis" in issue for issue in issues)

    def test_r4_missing_confidence_assumed_and_flagged(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        mystery = next(p for p in report.predictions if p.claim == "Mystery prediction")
        assert mystery.confidence == pytest.approx(0.5)
        assert "confidence_assumed" in mystery.flags
        assert any("missing confidence" in issue for issue in issues)

    def test_r5_recommendation_fields_patched(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        rec = report.recommendations[0]
        assert rec.action.strip()
        assert rec.expected_impact.strip()
        assert "missing_action" in rec.flags
        assert "missing_impact" in rec.flags
        assert any("missing_action" in issue for issue in issues)
        assert any("missing_impact" in issue for issue in issues)

    def test_r6_empty_chart_dropped(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        assert [c.id for c in report.charts] == ["chart_ok"]
        assert any("empty_chart" in issue for issue in issues)

    def test_r7_insights_resorted_after_downgrades(self) -> None:
        report, _ = run_critic_checklist(_weak_report_dict())
        weights = [i.strength.weight for i in report.insights]
        assert weights == sorted(weights, reverse=True)
        # 'Overclaim' (medium) now leads; the two low insights trail.
        assert report.insights[0].title == "Overclaim"


class TestCleanReports:
    """A well-evidenced report passes the checklist untouched."""

    def test_churn_report_is_clean(self) -> None:
        report_dict = build_report(churn_run())
        checked, issues = run_critic_checklist(report_dict)
        assert issues == []
        assert checked.meta["critic_clean"] is True

    def test_clean_report_flags_untouched(self) -> None:
        report_dict = build_report(churn_run())
        checked, _ = run_critic_checklist(report_dict)
        assert all(i.flags == [] for i in checked.insights)


class TestBuildIntegration:
    """build_report runs the checklist before summarizing."""

    def test_unsupported_run_gets_flagged(self) -> None:
        report = build_report(unsupported_claims_run())
        flagged = [i for i in report["insights"] if i["flags"]]
        assert flagged, "absolute-language insights must be flagged"
        assert any("absolute_claim" in i["flags"] for i in report["insights"])
        assert report["meta"]["critic_issues"]
        assert report["meta"]["critic_clean"] is False

    def test_unsupported_run_flags_not_endorsed_in_summary(self) -> None:
        report = build_report(unsupported_claims_run())
        summary = report["executive_summary"]
        assert "without endorsement" in summary

    def test_empty_chart_dropped_during_build(self) -> None:
        report = build_report(unsupported_claims_run())
        assert report["charts"] == []
        assert any("empty_chart" in issue for issue in report["meta"]["critic_issues"])

    def test_prediction_basis_always_present_after_build(self) -> None:
        report = build_report(unsupported_claims_run())
        for prediction in report["predictions"]:
            assert prediction["basis"].strip()


class TestInputs:
    """Input handling: Report models, dicts, bad types."""

    def test_accepts_report_model(self) -> None:
        model = Report(
            title="R",
            insights=[{"title": "t", "detail": "no numbers here at all", "evidence": []}],
        )
        report, issues = run_critic_checklist(model)
        assert isinstance(report, Report)
        assert issues  # the evidence-less insight is flagged

    def test_rejects_non_report_types(self) -> None:
        with pytest.raises(ValueError):
            run_critic_checklist("not a report")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            run_critic_checklist(42)  # type: ignore[arg-type]

    def test_issues_also_written_to_meta(self) -> None:
        report, issues = run_critic_checklist(_weak_report_dict())
        assert report.meta["critic_issues"] == issues
        assert report.meta["critic_clean"] is False

    def test_alias_short_form(self) -> None:
        from orchestrator.report import critic_checklist

        assert critic_checklist is run_critic_checklist
