"""orchestrator.report — the AgentForge insight engine (Agent 6).

Turns a finished agent run into the pinned structured deliverable:

    from orchestrator.report import build_report, render_markdown, export_pdf

    report = build_report(run_result.to_dict(), style="sales_insights")
    markdown_text = render_markdown(report)
    pdf_path = export_pdf(report, "runs/abc/report.pdf")

Public surface:
    build_report        — run dict -> pinned report dict (deterministic)
    render_markdown     — report -> GitHub-flavored Markdown
    export_pdf          — report or markdown -> PDF file via fpdf2
    run_critic_checklist — critic-agent checklist; rejects unsupported claims
    models              — pydantic Report/Insight/Prediction/Recommendation/ChartSpec
    styles              — per-team style profiles (section order, emphasis)

Only stdlib + pydantic + fpdf2 + markdown are imported here; the subpackage
never imports orchestrator core modules at import time (the optional LLM
polish import inside build.py is guarded and off unless LLM_MODE=live).
"""

from __future__ import annotations

from . import models, styles
from .build import build_report
from .critic_checklist import critic_checklist, run_critic_checklist
from .export_pdf import export_pdf
from .models import (
    ChartSpec,
    Effort,
    Insight,
    Prediction,
    Recommendation,
    Report,
    Strength,
    coerce_report,
)
from .render_markdown import render_markdown
from .styles import StyleProfile, get_style, list_styles

__all__ = [
    "build_report",
    "render_markdown",
    "export_pdf",
    "run_critic_checklist",
    "critic_checklist",
    "models",
    "styles",
    "Report",
    "Insight",
    "Prediction",
    "Recommendation",
    "ChartSpec",
    "Strength",
    "Effort",
    "coerce_report",
    "StyleProfile",
    "get_style",
    "list_styles",
]

__version__ = "1.0.0"
