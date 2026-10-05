"""Tests for orchestrator.report.models — pinned Report model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.report.models import (
    ChartSpec,
    Effort,
    Insight,
    Prediction,
    Recommendation,
    Report,
    Strength,
    coerce_report,
)


class TestStrengthAndEffort:
    """Evidence-strength and effort enums (pinned values)."""

    def test_strength_values_are_pinned(self) -> None:
        assert {s.value for s in Strength} == {"high", "medium", "low"}

    def test_strength_weight_orders_ranking(self) -> None:
        assert Strength.HIGH.weight > Strength.MEDIUM.weight > Strength.LOW.weight

    def test_effort_values_are_pinned(self) -> None:
        assert {e.value for e in Effort} == {"S", "M", "L"}

    def test_effort_cost_orders_matrix(self) -> None:
        assert Effort.S.cost < Effort.M.cost < Effort.L.cost


class TestInsight:
    """Insight coercion + validation."""

    def test_minimal_insight_defaults(self) -> None:
        insight = Insight(title="Churn is up 9.8%")
        assert insight.detail == ""
        assert insight.evidence == []
        assert insight.strength == Strength.LOW
        assert insight.flags == []

    def test_blank_title_falls_back(self) -> None:
        insight = Insight(title="   ", detail="Some detail")
        assert insight.title == "(untitled insight)"

    def test_strength_coercion_case_insensitive(self) -> None:
        assert Insight(title="t", strength="HIGH").strength == Strength.HIGH
        assert Insight(title="t", strength="Medium").strength == Strength.MEDIUM

    def test_unknown_strength_maps_to_low(self) -> None:
        assert Insight(title="t", strength="certain").strength == Strength.LOW

    def test_evidence_from_bare_string(self) -> None:
        insight = Insight(title="t", evidence="chart artifact 'c'")
        assert insight.evidence == ["chart artifact 'c'"]

    def test_evidence_drops_blank_items(self) -> None:
        insight = Insight(title="t", evidence=["a", "", None, "b"])
        assert insight.evidence == ["a", "b"]

    def test_detail_coerces_numbers(self) -> None:
        insight = Insight(title="t", detail=42)
        assert insight.detail == "42"


class TestPrediction:
    """Prediction confidence coercion and clamping."""

    def test_confidence_percent_string(self) -> None:
        assert Prediction(claim="c", confidence="82%").confidence == pytest.approx(0.82)

    def test_confidence_decimal_string(self) -> None:
        assert Prediction(claim="c", confidence="0.55").confidence == pytest.approx(0.55)

    def test_confidence_above_one_is_percent(self) -> None:
        assert Prediction(claim="c", confidence=87).confidence == pytest.approx(0.87)

    def test_confidence_clamped(self) -> None:
        assert Prediction(claim="c", confidence=1.5).confidence == 1.0
        assert Prediction(claim="c", confidence=-3).confidence == 0.0

    def test_confidence_garbage_defaults_midpoint(self) -> None:
        assert Prediction(claim="c", confidence="nonsense").confidence == pytest.approx(0.5)

    def test_confidence_just_above_one_clamps(self) -> None:
        # 1.2 is not a sane percentage; it clamps to the ceiling instead.
        assert Prediction(claim="c", confidence=1.2).confidence == 1.0

    def test_confidence_two_reads_as_two_percent(self) -> None:
        # >1.5 is read as a percentage (2.0 -> 2%), matching '87' -> 0.87.
        assert Prediction(claim="c", confidence=2.0).confidence == pytest.approx(0.02)

    def test_confidence_nan_defaults_midpoint(self) -> None:
        assert Prediction(claim="c", confidence=float("nan")).confidence == pytest.approx(0.5)

    def test_confidence_required_per_pinned_contract(self) -> None:
        with pytest.raises(ValidationError):
            Prediction(claim="c")  # confidence has no default in the pinned model


class TestRecommendation:
    """Recommendation effort/priority validation (priority 1 = do first)."""

    def test_effort_aliases(self) -> None:
        assert Recommendation(title="t", effort="small").effort == Effort.S
        assert Recommendation(title="t", effort="m").effort == Effort.M
        assert Recommendation(title="t", effort="large").effort == Effort.L

    def test_unknown_effort_maps_to_medium(self) -> None:
        assert Recommendation(title="t", effort="huge").effort == Effort.M

    def test_priority_clamped_to_range(self) -> None:
        assert Recommendation(title="t", priority=99).priority == 5
        assert Recommendation(title="t", priority=-2).priority == 1

    def test_priority_garbage_defaults(self) -> None:
        assert Recommendation(title="t", priority="soon").priority == 3

    def test_default_priority_is_three(self) -> None:
        assert Recommendation(title="t").priority == 3


class TestChartSpec:
    """ChartSpec passthrough with pinned kinds."""

    def test_valid_spec(self) -> None:
        spec = ChartSpec(
            id="chart_1",
            kind="bar",
            title="Churn",
            data=[{"label": "M2M", "x": 1, "y": 18.4}],
        )
        assert spec.id == "chart_1"
        assert spec.data[0]["y"] == 18.4

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChartSpec(id="chart_2", kind="hologram", data=[])

    def test_blank_id_gets_placeholder(self) -> None:
        assert ChartSpec(id="  ", kind="pie").id == "chart_unknown"

    def test_list_points_mapped_positionally(self) -> None:
        spec = ChartSpec(id="chart_3", kind="line", data=[["Jan", 1, 10]])
        assert spec.data[0] == {"label": "Jan", "x": 1, "y": 10}

    def test_dict_input_wrapped(self) -> None:
        spec = ChartSpec(id="chart_4", kind="bar", data={"label": "a", "x": 1, "y": 2})
        assert spec.data == [{"label": "a", "x": 1, "y": 2}]


class TestReport:
    """Report-level coercion and section tolerance."""

    def test_pinned_shape_round_trip(self) -> None:
        report = Report(
            title="R",
            mission="m",
            style="sales_insights",
            executive_summary="s",
            insights=[{"title": "i", "detail": "d", "evidence": ["e"], "strength": "high"}],
            charts=[{"id": "chart_1", "kind": "bar", "data": [{"label": "x"}]}],
            predictions=[{"claim": "p", "confidence": 0.7, "basis": "b"}],
            recommendations=[
                {"title": "r", "action": "a", "expected_impact": "i", "effort": "S", "priority": 1}
            ],
            appendix="x",
        )
        dumped = report.model_dump(mode="json")
        for key in (
            "title",
            "mission",
            "style",
            "executive_summary",
            "insights",
            "charts",
            "predictions",
            "recommendations",
            "appendix",
        ):
            assert key in dumped
        assert dumped["insights"][0]["strength"] == "high"
        assert dumped["recommendations"][0]["priority"] == 1

    def test_none_sections_become_empty_lists(self) -> None:
        report = Report(title="R", insights=None, charts=None)  # type: ignore[arg-type]
        assert report.insights == []
        assert report.charts == []

    def test_blank_title_defaults(self) -> None:
        assert Report(title="").title == "AgentForge Report"

    def test_unknown_style_lowercased_not_rejected(self) -> None:
        assert Report(title="R", style="WEIRD").style == "weird"

    def test_coerce_report_accepts_dict(self) -> None:
        report = coerce_report({"title": "R", "predictions": None})
        assert isinstance(report, Report)

    def test_coerce_report_accepts_model(self) -> None:
        model = Report(title="R")
        assert coerce_report(model) is model

    def test_coerce_report_rejects_other_types(self) -> None:
        with pytest.raises(ValueError):
            coerce_report("not a report")  # type: ignore[arg-type]
