"""Critic-agent checklist for AgentForge reports (Agent 6).

The critic's job is to REJECT unsupported claims before a report reaches a
human. :func:`run_critic_checklist` scans a report (dict or :class:`Report`)
and enforces these rules:

R1 ``unsupported_claim``   — insight with zero evidence refs AND no numeric
                             grounding: strength downgraded to ``low`` + flag.
R2 ``overclaim``           — insight marked ``high`` with fewer than 2 evidence
                             refs and no numeric grounding: downgraded to
                             ``medium`` + flag.
R3 ``absolute_claim``      — absolute language ("guaranteed", "always", ...)
                             without a citation marker: strength downgraded to
                             ``low`` + flag (predictions: confidence capped).
R4 ``missing_prediction_basis`` — every prediction must have ``confidence`` and
                             ``basis``; missing basis is patched honestly and
                             flagged, missing confidence is assumed 0.5 and
                             flagged.
R5 ``missing_recommendation_fields`` — every recommendation must have
                             ``action`` and ``expected_impact``; missing fields
                             are patched with honest placeholders + flags.
R6 ``empty_chart``         — charts with no data points are dropped.
R7 ranking hygiene         — insights are re-sorted strongest-first after
                             downgrades so the ranked invariant holds.

Returns ``(report, issues)`` where ``issues`` is a list of human-readable
problem strings (empty when the report is clean). This module is fully
deterministic — no LLM calls — and is safe to run standalone as the critic
agent's checklist tool.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from .models import ChartSpec, Prediction, Report, Strength

__all__ = ["run_critic_checklist", "critic_checklist"]

_ABSOLUTE_PATTERN: re.Pattern[str] = re.compile(
    r"\b("
    r"guaranteed?|guarantees|always|never|certainly|definitely|undoubtedly|"
    r"unquestionably|impossible|100\s*%|everyone|no\s+one|"
    r"every\s+customer|all\s+users|every\s+user|all\s+customers"
    r")\b",
    re.IGNORECASE,
)
_CITATION_PATTERN: re.Pattern[str] = re.compile(
    r"\b(according to|per|source[sd]?|cited|reported|dataset|data shows)\b",
    re.IGNORECASE,
)
_NUMERIC_PATTERN: re.Pattern[str] = re.compile(
    r"(\d+(\.\d+)?\s*%)"          # percentages: 9.8%, 12 %
    r"|(\$|€|£)\s*\d+"            # money: $4200
    r"|(\b\d+\.\d+\b)"            # decimals: 4.2
    r"|(\b\d{2,}\b)"              # multi-digit counts: 1200
)

_PREDICTION_ABSOLUTE_CONFIDENCE_CAP = 0.6
"""Absolute-language predictions get their confidence capped here."""


def _has_numeric_grounding(text: str) -> bool:
    """True when ``text`` contains a number that reads as real evidence."""
    return bool(_NUMERIC_PATTERN.search(text or ""))


def _is_cited(text: str, evidence_count: int) -> bool:
    """True when a claim carries a real citation.

    Auto-generated artifact refs alone are not accepted as citations for
    absolute language: alongside them we require numeric grounding or an
    explicit source phrase ("according to", "source:", "reported", ...).
    """
    combined = text or ""
    if evidence_count > 0:
        return bool(
            _NUMERIC_PATTERN.search(combined) or _CITATION_PATTERN.search(combined)
        )
    return bool(_CITATION_PATTERN.search(combined))


def _normalize_raw_report(raw: dict) -> dict:
    """Pre-validate repair for sloppy external report dicts.

    Fills missing prediction confidence (0.5, flagged ``confidence_assumed``)
    and missing recommendation action/expected-impact fields so
    :class:`Report` validation does not blow up before the checklist can
    record honest issues. Mutates nothing: returns a shallow-copied,
    repaired dict.
    """
    repaired: dict = dict(raw)
    predictions: list = []
    for pred in repaired.get("predictions") or []:
        if isinstance(pred, dict):
            item = dict(pred)
            if "confidence" not in item or item["confidence"] is None:
                item["confidence"] = 0.5
                flags = list(item.get("flags") or [])
                if "confidence_assumed" not in flags:
                    flags.append("confidence_assumed")
                item["flags"] = flags
            if item.get("basis") is None:
                item["basis"] = ""
            predictions.append(item)
        else:
            predictions.append(pred)
    repaired["predictions"] = predictions

    recommendations: list = []
    for rec in repaired.get("recommendations") or []:
        if isinstance(rec, dict):
            item = dict(rec)
            item.setdefault("action", "")
            item.setdefault("expected_impact", "")
            recommendations.append(item)
        else:
            recommendations.append(rec)
    repaired["recommendations"] = recommendations
    return repaired


def _load_report(source: "Report | dict") -> tuple[Report, list[str]]:
    """Coerce ``source`` into a Report, ready for checking.

    Dict sources are normalized first (missing confidences flagged, missing
    recommendation fields defaulted) so the checklist can report them as
    honest issues instead of crashing on validation.
    """
    if isinstance(source, Report):
        return source, []
    if not isinstance(source, dict):
        raise ValueError(
            f"critic_checklist expects a Report or dict, got {type(source).__name__}"
        )
    try:
        return Report.model_validate(_normalize_raw_report(source)), []
    except ValidationError as exc:
        raise ValueError(f"report dict is not a valid Report: {exc}") from exc


def _scrub_insight(index: int, insight, issues: list[str]) -> None:
    """Apply R1-R3 to one insight, mutating strength/flags in place."""
    combined_text = f"{insight.title} {insight.detail}"
    evidence_count = len(insight.evidence)
    numeric = _has_numeric_grounding(combined_text)

    # R1: unsupported claim — nothing points at evidence and no numbers.
    if evidence_count == 0 and not numeric:
        if "unsupported_claim" not in insight.flags:
            insight.flags.append("unsupported_claim")
        if insight.strength != Strength.LOW:
            insight.strength = Strength.LOW
        issues.append(
            f"insight[{index}] '{insight.title}': unsupported_claim — no evidence "
            "refs and no numeric grounding; strength downgraded to low"
        )

    # R2: overclaim — 'high' needs corroboration (2+ refs) or numbers.
    elif insight.strength == Strength.HIGH and evidence_count < 2 and not numeric:
        if "overclaim" not in insight.flags:
            insight.flags.append("overclaim")
        insight.strength = Strength.MEDIUM
        issues.append(
            f"insight[{index}] '{insight.title}': overclaim — strength 'high' "
            f"but only {evidence_count} evidence ref(s) and no numeric grounding; "
            "downgraded to medium"
        )

    # R3: absolute language without a citation.
    if _ABSOLUTE_PATTERN.search(combined_text) and not _is_cited(
        combined_text, evidence_count
    ):
        if "absolute_claim" not in insight.flags:
            insight.flags.append("absolute_claim")
        if insight.strength != Strength.LOW:
            insight.strength = Strength.LOW
            issues.append(
                f"insight[{index}] '{insight.title}': absolute_claim — absolute "
                "language without a citation; strength downgraded to low"
            )
        else:
            issues.append(
                f"insight[{index}] '{insight.title}': absolute_claim — absolute "
                "language without a citation"
            )


def _scrub_prediction(index: int, prediction: Prediction, issues: list[str]) -> None:
    """Apply R3/R4 to one prediction, patching honestly where possible."""
    # R4a: missing confidence (only reachable via the raw-dict repair path).
    if prediction.flags and "confidence_assumed" in prediction.flags:
        issues.append(
            f"prediction[{index}]: missing confidence — assumed 0.5; "
            "verify against the producing agent's output"
        )

    # R4b: missing basis.
    if not prediction.basis.strip():
        if prediction.evidence:
            prediction.basis = (
                "Basis not recorded by the producing agent; derived from: "
                + "; ".join(prediction.evidence)
            )
        else:
            prediction.basis = (
                "Basis not recorded by the producing agent "
                "(no evidence references were attached to this prediction)."
            )
        if "missing_basis" not in prediction.flags:
            prediction.flags.append("missing_basis")
        issues.append(
            f"prediction[{index}] '{prediction.claim[:60]}...': "
            "missing_prediction_basis — basis patched with an honest placeholder"
        )

    # R3 for predictions: absolute language caps confidence.
    combined = f"{prediction.claim} {prediction.basis}"
    if _ABSOLUTE_PATTERN.search(combined) and not _is_cited(
        prediction.claim, len(prediction.evidence)
    ):
        if "absolute_claim" not in prediction.flags:
            prediction.flags.append("absolute_claim")
        if prediction.confidence > _PREDICTION_ABSOLUTE_CONFIDENCE_CAP:
            prediction.confidence = _PREDICTION_ABSOLUTE_CONFIDENCE_CAP
            issues.append(
                f"prediction[{index}]: absolute_claim — absolute language without "
                f"a citation; confidence capped at {_PREDICTION_ABSOLUTE_CONFIDENCE_CAP}"
            )
        else:
            issues.append(
                f"prediction[{index}]: absolute_claim — absolute language without "
                "a citation"
            )


def _scrub_recommendation(index: int, rec, issues: list[str]) -> None:
    """Apply R5 to one recommendation, patching honestly where possible."""
    if not rec.action.strip():
        rec.action = f"Execute: {rec.title}"
        if "missing_action" not in rec.flags:
            rec.flags.append("missing_action")
        issues.append(
            f"recommendation[{index}] '{rec.title}': missing_action — action "
            "patched from the title; review before acting"
        )
    if not rec.expected_impact.strip():
        rec.expected_impact = "Impact not yet quantified by the producing agent."
        if "missing_impact" not in rec.flags:
            rec.flags.append("missing_impact")
        issues.append(
            f"recommendation[{index}] '{rec.title}': missing_impact — expected "
            "impact patched with an honest placeholder"
        )


def run_critic_checklist(source: "Report | dict") -> tuple[Report, list[str]]:
    """Run the critic checklist over a report.

    Args:
        source: A :class:`~orchestrator.report.models.Report` or a report dict
            (the pinned shape, or a sloppier variant — repaired first).

    Returns:
        Tuple of ``(report, issues)``: the checked/patched :class:`Report`
        (same object when a Report was passed in) and a list of human-readable
        issue strings, empty when the report is clean.

    Raises:
        ValueError: if ``source`` is not a Report/dict, or cannot be coerced.
    """
    report, issues = _load_report(source)

    # Insights: R1-R3.
    for index, insight in enumerate(report.insights):
        _scrub_insight(index, insight, issues)

    # Predictions: R3/R4.
    for index, prediction in enumerate(report.predictions):
        _scrub_prediction(index, prediction, issues)

    # Recommendations: R5.
    for index, rec in enumerate(report.recommendations):
        _scrub_recommendation(index, rec, issues)

    # Charts: R6 — drop empty ones (they cannot be rendered meaningfully).
    kept_charts: list[ChartSpec] = []
    for index, chart in enumerate(report.charts):
        if not chart.data:
            issues.append(
                f"chart[{index}] '{chart.title or chart.id}': empty_chart — no "
                "data points; chart dropped from the report"
            )
            continue
        kept_charts.append(chart)
    report.charts = kept_charts

    # R7: re-sort insights strongest-first after any downgrades (stable).
    report.insights = sorted(
        report.insights, key=lambda i: -i.strength.weight
    ) if report.insights else []

    report.meta = dict(report.meta) if isinstance(report.meta, dict) else {}
    report.meta["critic_issues"] = list(issues)
    report.meta["critic_clean"] = not issues
    return report, issues


#: Alias matching the module name for callers that prefer the short form.
critic_checklist = run_critic_checklist
