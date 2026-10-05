"""Report style profiles for the AgentForge template marketplace (Agent 6).

A :class:`StyleProfile` tells :mod:`orchestrator.report.build` and
:mod:`orchestrator.report.render_markdown` how a report for one of the three
marketplace teams is shaped: section ordering, executive-summary emphasis,
and which sections are required for that team.

Pure data + stdlib; consumed by ``build.py`` and ``render_markdown.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["StyleProfile", "get_style", "list_styles", "STYLE_NAMES"]

STYLE_NAMES: tuple[str, ...] = (
    "default",
    "market_research",
    "sales_insights",
    "support_triage",
)
"""Exact style ids accepted by ``build_report(style=...)``."""


@dataclass(frozen=True)
class StyleProfile:
    """Declarative shape of a report for one team template.

    Attributes:
        name: Style id (pinned value used in ``Report.style``).
        display_name: Human-readable name shown in the report appendix.
        description: One-line description of the team's focus.
        section_order: Render order of report sections (by pinned key).
        required_sections: Sections that must be non-empty for this style;
            build_report notes any that came out empty (honesty rule).
        exec_summary_emphasis: Which block leads the executive summary:
            ``insights`` | ``predictions`` | ``recommendations``.
        exec_summary_max_insights: How many top insight titles the summary cites.
        max_insights: Cap on insights kept in the final report.
        max_predictions: Cap on predictions kept.
        max_recommendations: Cap on recommendations kept.
        top_n_recommendations: How many recommendations the summary cites.
        summary_vocabulary: Noun used for this team's key findings.
    """

    name: str
    display_name: str
    description: str
    section_order: tuple[str, ...] = (
        "executive_summary",
        "insights",
        "charts",
        "predictions",
        "recommendations",
        "appendix",
    )
    required_sections: tuple[str, ...] = ("insights",)
    exec_summary_emphasis: str = "insights"
    exec_summary_max_insights: int = 3
    max_insights: int = 12
    max_predictions: int = 8
    max_recommendations: int = 6
    top_n_recommendations: int = 2
    summary_vocabulary: str = "insight"


_DEFAULT = StyleProfile(
    name="default",
    display_name="Default Analysis Team",
    description="Balanced report shape for any business mission.",
    section_order=(
        "executive_summary",
        "insights",
        "charts",
        "predictions",
        "recommendations",
        "appendix",
    ),
    required_sections=("insights",),
    exec_summary_emphasis="insights",
    exec_summary_max_insights=3,
    max_insights=12,
    max_predictions=8,
    max_recommendations=6,
    top_n_recommendations=2,
    summary_vocabulary="insight",
)

_MARKET_RESEARCH = StyleProfile(
    name="market_research",
    display_name="Market Research Team",
    description="Signal-hunting team: evidence and charts lead the story.",
    section_order=(
        "executive_summary",
        "insights",
        "charts",
        "predictions",
        "recommendations",
        "appendix",
    ),
    required_sections=("insights", "charts"),
    exec_summary_emphasis="insights",
    exec_summary_max_insights=3,
    max_insights=14,
    max_predictions=6,
    max_recommendations=6,
    top_n_recommendations=2,
    summary_vocabulary="market signal",
)

_SALES_INSIGHTS = StyleProfile(
    name="sales_insights",
    display_name="Sales Insights Team",
    description="Revenue-focused team: ranked recommendations lead the story.",
    section_order=(
        "executive_summary",
        "insights",
        "recommendations",
        "charts",
        "predictions",
        "appendix",
    ),
    required_sections=("insights", "recommendations"),
    exec_summary_emphasis="recommendations",
    exec_summary_max_insights=2,
    max_insights=10,
    max_predictions=8,
    max_recommendations=8,
    top_n_recommendations=3,
    summary_vocabulary="sales insight",
)

_SUPPORT_TRIAGE = StyleProfile(
    name="support_triage",
    display_name="Support Triage Team",
    description="Volume-triage team: forecasts and triage actions lead the story.",
    section_order=(
        "executive_summary",
        "insights",
        "predictions",
        "recommendations",
        "charts",
        "appendix",
    ),
    required_sections=("insights", "recommendations"),
    exec_summary_emphasis="predictions",
    exec_summary_max_insights=2,
    max_insights=10,
    max_predictions=10,
    max_recommendations=6,
    top_n_recommendations=3,
    summary_vocabulary="triage finding",
)

_PROFILES: dict[str, StyleProfile] = {
    _DEFAULT.name: _DEFAULT,
    _MARKET_RESEARCH.name: _MARKET_RESEARCH,
    _SALES_INSIGHTS.name: _SALES_INSIGHTS,
    _SUPPORT_TRIAGE.name: _SUPPORT_TRIAGE,
}


def get_style(name: str | None) -> StyleProfile:
    """Return the profile for ``name``; unknown names fall back to ``default``.

    Args:
        name: One of :data:`STYLE_NAMES` (case-insensitive) or ``None``. A
            marketplace template id (``market_research_team`` ...) is also
            accepted: the trailing ``_team`` suffix is stripped before lookup,
            matching how the engine passes ``template_id`` straight through as
            the report style.

    Returns:
        The matching :class:`StyleProfile`, or the default profile when the
        name is unknown/empty. Callers can detect the fallback by comparing
        ``profile.name != requested``.
    """
    if not name:
        return _DEFAULT
    key = str(name).strip().lower()
    if key.endswith("_team"):
        key = key[: -len("_team")]
    return _PROFILES.get(key, _DEFAULT)


def list_styles() -> list[StyleProfile]:
    """Return all four profiles in pinned order (default first)."""
    return [_PROFILES[name] for name in STYLE_NAMES]
