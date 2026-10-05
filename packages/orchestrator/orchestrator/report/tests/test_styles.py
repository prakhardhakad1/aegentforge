"""Tests for orchestrator.report.styles — per-team style profiles."""

from __future__ import annotations

import pytest

from orchestrator.report.styles import STYLE_NAMES, StyleProfile, get_style, list_styles


class TestRegistry:
    """The four pinned profiles are registered and ordered."""

    def test_pinned_style_names(self) -> None:
        assert STYLE_NAMES == (
            "default",
            "market_research",
            "sales_insights",
            "support_triage",
        )

    def test_list_styles_covers_all_in_order(self) -> None:
        profiles = list_styles()
        assert [p.name for p in profiles] == list(STYLE_NAMES)

    @pytest.mark.parametrize("name", list(STYLE_NAMES))
    def test_lookup_by_name(self, name: str) -> None:
        assert get_style(name).name == name

    def test_lookup_case_insensitive(self) -> None:
        assert get_style("SALES_INSIGHTS").name == "sales_insights"

    def test_none_and_empty_fall_back_to_default(self) -> None:
        assert get_style(None).name == "default"
        assert get_style("").name == "default"

    def test_unknown_falls_back_to_default(self) -> None:
        assert get_style("growth_hacking").name == "default"

    def test_team_template_ids_map_to_profiles(self) -> None:
        """The engine passes template_id (e.g. 'sales_insights_team') as style."""
        assert get_style("market_research_team").name == "market_research"
        assert get_style("sales_insights_team").name == "sales_insights"
        assert get_style("support_triage_team").name == "support_triage"


class TestProfileShape:
    """Profiles differ in the ways that matter to the renderers."""

    def test_sales_emphasizes_recommendations(self) -> None:
        profile = get_style("sales_insights")
        assert profile.exec_summary_emphasis == "recommendations"
        assert profile.section_order.index("recommendations") < profile.section_order.index(
            "charts"
        )

    def test_support_emphasizes_predictions(self) -> None:
        profile = get_style("support_triage")
        assert profile.exec_summary_emphasis == "predictions"
        assert profile.section_order.index("predictions") < profile.section_order.index(
            "charts"
        )

    def test_market_research_requires_charts(self) -> None:
        profile = get_style("market_research")
        assert "charts" in profile.required_sections
        assert profile.summary_vocabulary == "market signal"

    def test_all_profiles_have_required_sections(self) -> None:
        for profile in list_styles():
            assert profile.required_sections
            assert set(profile.required_sections) <= {
                "insights",
                "charts",
                "predictions",
                "recommendations",
            }

    def test_section_orders_cover_all_sections(self) -> None:
        expected = {
            "executive_summary",
            "insights",
            "charts",
            "predictions",
            "recommendations",
            "appendix",
        }
        for profile in list_styles():
            assert set(profile.section_order) == expected

    def test_profiles_are_frozen(self) -> None:
        profile = get_style("default")
        with pytest.raises(Exception):
            profile.max_insights = 1  # type: ignore[misc]

    def test_is_dataclass(self) -> None:
        assert isinstance(get_style("default"), StyleProfile)
