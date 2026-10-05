"""GitHub-flavored Markdown renderer for AgentForge reports (Agent 6).

    render_markdown(report: dict | Report) -> str

Produces a polished GFM document: title, mission blockquote, executive
summary, insight sections with strength badges, chart references (embedded
image links when the artifact file path exists, plus a data table so charts
survive without images), a prediction table with confidence percentages, a
priority-ordered recommendation table, and the appendix.

Section order follows the report's style profile (``styles/``), falling back
to the pinned default order. Tolerant of missing keys: a half-formed report
dict still renders.
"""

from __future__ import annotations

import os
from typing import Any

from .models import Report, coerce_report
from .styles import StyleProfile, get_style

__all__ = ["render_markdown"]

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def _esc(text: Any) -> str:
    """Escape cell-hostile characters (pipes, newlines) for GFM tables."""
    if text is None:
        return ""
    return " ".join(str(text).replace("|", "\\|").split())


def _badge(strength: str) -> str:
    """Uppercase strength badge, e.g. ``**[HIGH]**``."""
    return f"**[{str(strength).upper()}]**"


def _chart_image_link(chart) -> str | None:
    """Markdown image link when the chart artifact file exists on disk."""
    path = getattr(chart, "path", None)
    if not path:
        return None
    candidates = [path, os.path.join(os.getcwd(), path)]
    for candidate in candidates:
        try:
            if os.path.isfile(candidate):
                return f"![{_esc(chart.title or chart.id)}]({candidate})"
        except OSError:
            continue
    return None


def _render_chart_table(chart) -> list[str]:
    """Small data table for a chart (first 12 points) so it reads without the image."""
    lines: list[str] = []
    points = chart.data[:12]
    if not points:
        return lines
    lines.append("| Label | X | Y |")
    lines.append("|---|---|---|")
    for point in points:
        label = _esc(point.get("label", ""))
        x_value = _esc(point.get("x", ""))
        y_value = _esc(point.get("y", ""))
        lines.append(f"| {label} | {x_value} | {y_value} |")
    if len(chart.data) > 12:
        lines.append(f"*(...and {len(chart.data) - 12} more points)*")
    return lines


def _render_insights(report: Report) -> list[str]:
    """Key-insights section with strength badges and evidence lines."""
    lines: list[str] = ["## Key Insights", ""]
    if not report.insights:
        lines.append("*No insights were extracted from this run.*")
        lines.append("")
        return lines
    for index, insight in enumerate(report.insights, start=1):
        flags = "".join(f" `~{flag}`" for flag in insight.flags)
        lines.append(f"### {index}. {_esc(insight.title)} {_badge(insight.strength.value)}{flags}")
        lines.append("")
        lines.append(insight.detail if insight.detail else "*(no detail recorded)*")
        lines.append("")
        if insight.evidence:
            lines.append("*Evidence:* " + "; ".join(_esc(e) for e in insight.evidence))
            lines.append("")
    return lines


def _render_charts(report: Report) -> list[str]:
    """Charts section: image link when available + data table + notes."""
    lines: list[str] = ["## Charts", ""]
    if not report.charts:
        lines.append("*No charts were produced by this run.*")
        lines.append("")
        return lines
    for chart in report.charts:
        lines.append(f"### {_esc(chart.title or chart.id)}")
        lines.append("")
        meta_bits = [b for b in (chart.x_label, chart.y_label) if b]
        if meta_bits:
            lines.append(f"*Axes: {' vs '.join(_esc(b) for b in meta_bits)}*")
            lines.append("")
        image_link = _chart_image_link(chart)
        if image_link:
            lines.append(image_link)
            lines.append("")
        table_lines = _render_chart_table(chart)
        lines.extend(table_lines)
        if table_lines:
            lines.append("")
        if chart.notes:
            lines.append(f"*Notes: {_esc(chart.notes)}*")
            lines.append("")
    return lines


def _render_predictions(report: Report) -> list[str]:
    """Predictions table with confidence percentages."""
    lines: list[str] = ["## Predictions", ""]
    if not report.predictions:
        lines.append("*No predictions were produced by this run.*")
        lines.append("")
        return lines
    lines.append("| # | Prediction | Confidence | Basis |")
    lines.append("|---|---|---|---|")
    for index, prediction in enumerate(report.predictions, start=1):
        pct = f"{int(round(prediction.confidence * 100))}%"
        flag_note = " *(critic-flagged)*" if prediction.flags else ""
        lines.append(
            f"| {index} | {_esc(prediction.claim)}{flag_note} | {pct} | {_esc(prediction.basis)} |"
        )
    lines.append("")
    return lines


def _render_recommendations(report: Report) -> list[str]:
    """Priority-ordered recommendations table."""
    lines: list[str] = ["## Recommendations", ""]
    if not report.recommendations:
        lines.append("*No recommendations were produced by this run.*")
        lines.append("")
        return lines
    ordered = sorted(report.recommendations, key=lambda r: r.priority)
    lines.append("| Priority | Recommendation | Action | Expected impact | Effort |")
    lines.append("|---|---|---|---|---|")
    for rec in ordered:
        lines.append(
            f"| {rec.priority} | {_esc(rec.title)} | {_esc(rec.action)} "
            f"| {_esc(rec.expected_impact)} | {rec.effort.value} |"
        )
    lines.append("")
    return lines


def _render_sections(report: Report, profile: StyleProfile) -> list[str]:
    """Render body sections in the style profile's order."""
    renderers = {
        "insights": _render_insights,
        "charts": _render_charts,
        "predictions": _render_predictions,
        "recommendations": _render_recommendations,
        "appendix": lambda r: ["## Appendix", "", r.appendix or "*(no appendix)*", ""],
    }
    lines: list[str] = []
    for section in profile.section_order:
        if section == "executive_summary":
            lines.append("## Executive Summary")
            lines.append("")
            lines.append(report.executive_summary or "*(no executive summary)*")
            lines.append("")
            continue
        renderer = renderers.get(section)
        if renderer is not None:
            lines.extend(renderer(report))
    # Any section not covered by the profile order still renders (pinned keys).
    for section, renderer in renderers.items():
        if section not in profile.section_order:
            lines.extend(renderer(report))
    return lines


def render_markdown(report: "dict[str, Any] | Report") -> str:
    """Render a report (dict or Report model) as GitHub-flavored Markdown.

    Args:
        report: The pinned report dict or a :class:`Report` instance.

    Returns:
        A GFM string: title, mission, exec summary, insights (strength
        badges), charts (image links + data tables), predictions table with
        confidence %, priority-ordered recommendations table, appendix.
    """
    validated: Report = coerce_report(report)
    profile = get_style(validated.style)

    lines: list[str] = [f"# {validated.title}", ""]
    if validated.mission:
        lines.append(f"> **Mission:** {validated.mission}")
        lines.append("")
    if validated.meta.get("style_profile"):
        lines.append(f"*Report style: {validated.meta['style_profile']} "
                     f"(`{validated.style}`)*")
        lines.append("")
    lines.extend(_render_sections(validated, profile))
    return "\n".join(lines).rstrip() + "\n"
