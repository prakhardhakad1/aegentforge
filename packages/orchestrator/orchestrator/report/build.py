"""build_report pipeline for AgentForge (Agent 6).

Turns a finished agent run (``RunResult.to_dict()`` shape per
``docs/INTERFACES.md``) into the pinned structured report dict:

    build_report(run_result: dict, style: str = "default") -> dict

Pipeline stages
---------------
1. Parse + normalize the run (mission, status, plan, steps, artifacts,
   token_usage, errors) defensively — a sloppy engine dict must never crash
   the report.
2. Collect artifacts by kind (text / prediction / recommendation / chart /
   table).
3. Extract candidate insights from artifact summaries and step outputs.
4. Rank insights by evidence strength (evidence-ref count and specificity,
   numeric support, cross-source corroboration) and cap per style profile.
5. Assemble charts (validated ChartSpecs; invalid ones are dropped, noted).
6. Assemble predictions (confidence in [0,1] + basis) and recommendations
   (impact/effort priority matrix, priority 1 = do first).
7. Run the critic checklist (rejects unsupported claims) — see
   :mod:`orchestrator.report.critic_checklist`.
8. Compose the executive summary as a deterministic template synthesis over
   the *scrubbed* report. Optional LLM polish happens only when
   ``LLM_MODE=live`` AND ``orchestrator.llm`` is importable; any failure
   silently falls back to the deterministic summary. Zero-LLM is the default
   and tested path.
9. Compose the appendix (mission, plan, token usage, run status, errors,
   data-coverage notes).

The result is ``Report.model_dump(mode="json")`` — plain JSON-safe dict.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .critic_checklist import run_critic_checklist
from .models import ChartSpec, Insight, Prediction, Recommendation, Report, Strength
from .styles import StyleProfile, get_style

__all__ = ["build_report"]

_PIPELINE_VERSION = "1.0.0"

_SENTENCE_SPLIT: re.Pattern[str] = re.compile(r"(?<=[.!?])\s+")
_PERCENT_IN_TEXT: re.Pattern[str] = re.compile(r"\d+(\.\d+)?\s*%")
_NUMERIC_GROUNDING: re.Pattern[str] = re.compile(
    r"(\d+(\.\d+)?\s*%)|((\$|€|£)\s*\d+)|(\b\d+\.\d+\b)|(\b\d{2,}\b)"
)
_HEDGES: re.Pattern[str] = re.compile(r"\b(maybe|might|possibly|perhaps|could)\b", re.IGNORECASE)
_RECO_STARTERS: re.Pattern[str] = re.compile(
    r"^\s*(we\s+)?(recommend|suggest|consider|should)\b", re.IGNORECASE
)
_IMPACT_HIGH: re.Pattern[str] = re.compile(
    r"\b(high|strong|major|significant|substantial|large)\b|(\d{2,}\s*%)|((\$|€|£)\s*\d+)",
    re.IGNORECASE,
)
_IMPACT_MEDIUM: re.Pattern[str] = re.compile(
    r"\b(moderate|medium|meaningful|solid|some)\b", re.IGNORECASE
)

# Ranking thresholds (see NOTES.md): score >= HIGH_AT -> high, >= MEDIUM_AT -> medium.
_HIGH_AT = 3.0
_MEDIUM_AT = 1.8


@dataclass
class _Candidate:
    """An unranked insight candidate extracted from run output."""

    title: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    score: float = 0.0
    numeric: bool = False


@dataclass
class _ParsedRun:
    """Normalized view of the engine's RunResult dict."""

    run_id: str = ""
    mission: str = ""
    status: str = "unknown"
    plan: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Run parsing / normalization
# ---------------------------------------------------------------------------


def _parse_run(run_result: dict) -> _ParsedRun:
    """Normalize a RunResult dict defensively (never raises on bad shapes)."""
    if not isinstance(run_result, dict):
        raise TypeError(
            f"build_report expects run_result: dict (RunResult.to_dict()), "
            f"got {type(run_result).__name__}"
        )
    parsed = _ParsedRun()
    parsed.run_id = str(run_result.get("run_id") or "")
    mission = run_result.get("mission")
    parsed.mission = str(mission).strip() if mission else ""
    parsed.status = str(run_result.get("status") or "unknown").strip().lower()
    parsed.plan = [p for p in (run_result.get("plan") or []) if isinstance(p, dict)]
    parsed.steps = [s for s in (run_result.get("steps") or []) if isinstance(s, dict)]
    parsed.artifacts = [
        a for a in (run_result.get("artifacts") or []) if isinstance(a, dict)
    ]
    usage = run_result.get("token_usage")
    parsed.token_usage = usage if isinstance(usage, dict) else {}
    raw_errors = run_result.get("errors") or []
    if isinstance(raw_errors, str):
        raw_errors = [raw_errors]
    parsed.errors = [str(e) for e in raw_errors if e]
    return parsed


def _artifact_field(artifact: dict, *names: str, default: Any = None) -> Any:
    """Read the first present key among ``names`` (artifacts vary by agent)."""
    for name in names:
        if name in artifact and artifact[name] is not None:
            return artifact[name]
    return default


def _artifact_id(artifact: dict, index: int) -> str:
    """Best-effort artifact id used for evidence references and chart ids."""
    raw = _artifact_field(artifact, "artifact_id", "id", default="")
    text = str(raw).strip() if raw is not None else ""
    return text or f"artifact_{index + 1}"


def _artifact_name(artifact: dict, index: int) -> str:
    """Best-effort artifact display name."""
    raw = _artifact_field(artifact, "name", "title", default="")
    text = str(raw).strip() if raw is not None else ""
    if text:
        return text
    summary = str(_artifact_field(artifact, "summary", default="") or "").strip()
    return _truncate(summary, 60) if summary else f"artifact {index + 1}"


def _truncate(text: str, limit: int) -> str:
    """Truncate at a word boundary with an ellipsis when too long."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut}..."


# ---------------------------------------------------------------------------
# Stage 2: collect artifacts by kind
# ---------------------------------------------------------------------------


def _collect_artifacts(artifacts: list[dict[str, Any]]) -> dict[str, list[tuple[int, dict]]]:
    """Group artifacts by their pinned kind, preserving run order."""
    grouped: dict[str, list[tuple[int, dict]]] = {}
    for index, artifact in enumerate(artifacts):
        kind = str(_artifact_field(artifact, "kind", default="file") or "file").strip().lower()
        grouped.setdefault(kind, []).append((index, artifact))
    return grouped


# ---------------------------------------------------------------------------
# Stage 3: extract insight candidates
# ---------------------------------------------------------------------------


def _sentences(text: str) -> list[str]:
    """Split text into sentences (best effort, abbreviation-tolerant enough)."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []
    parts = _SENTENCE_SPLIT.split(cleaned)
    return [p.strip() for p in parts if p.strip()]


def _is_insight_sentence(sentence: str) -> bool:
    """Filter sentences that would make noise rather than findings."""
    if not (25 <= len(sentence) <= 400):
        return False
    if sentence.endswith("?"):
        return False
    if _RECO_STARTERS.match(sentence):
        return False  # recommendations are handled by the rec assembler
    return True


def _make_candidate(
    detail: str,
    evidence: list[str],
    *,
    title_from: str | None = None,
) -> _Candidate:
    """Build a scored-candidate shell (score filled in stage 4)."""
    numeric = bool(_NUMERIC_GROUNDING.search(detail))
    title = title_from or _truncate(detail.rstrip(". "), 70)
    return _Candidate(title=title, detail=detail, evidence=list(evidence), numeric=numeric)


def _extract_from_artifacts(
    grouped: dict[str, list[tuple[int, dict]]]
) -> list[_Candidate]:
    """Candidates from text/table summaries, chart notes and predictions."""
    candidates: list[_Candidate] = []
    for kind in ("text", "table", "chart"):
        for index, artifact in grouped.get(kind, []):
            name = _artifact_name(artifact, index)
            summary = str(_artifact_field(artifact, "summary", "notes", default="") or "")
            evidence = [f"{kind} artifact '{name}'"]
            sentences = [s for s in _sentences(summary) if _is_insight_sentence(s)]
            for sentence in sentences[:4]:  # noise cap per artifact
                candidates.append(_make_candidate(sentence, evidence))
    for index, artifact in grouped.get("prediction", []):
        name = _artifact_name(artifact, index)
        data = _artifact_field(artifact, "data", "payload", "prediction", default={})
        claim = ""
        if isinstance(data, dict):
            claim = str(data.get("claim") or "").strip()
        if not claim:
            claim = str(_artifact_field(artifact, "summary", default="") or "").strip()
        if claim:
            candidates.append(
                _make_candidate(
                    claim if claim.endswith(".") else f"{claim}.",
                    [f"prediction artifact '{name}'"],
                    title_from=_truncate(f"Forecast: {claim}", 70),
                )
            )
    return candidates


def _step_summary(step: dict) -> str:
    """Pull the human-readable output text out of a step dict."""
    for key in ("summary", "thought_summary", "output", "result"):
        value = step.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            text = " ".join(str(v) for v in value.values() if v)
            if text.strip():
                return text.strip()
    return ""


def _extract_from_steps(
    steps: list[dict[str, Any]], grouped: dict[str, list[tuple[int, dict]]]
) -> list[_Candidate]:
    """Candidates from step outputs, cross-cited with that step's artifacts.

    A step that produced artifacts gets both the step and each artifact as
    evidence refs — that cross-source corroboration is what earns 'high'
    strength during ranking.
    """
    artifacts_by_subtask: dict[str, list[str]] = {}
    for index, artifact in grouped.get("text", []) + grouped.get("table", []) + grouped.get("chart", []):
        subtask = str(_artifact_field(artifact, "subtask_id", default="") or "")
        if not subtask:
            continue
        name = _artifact_name(artifact, index)
        kind = str(artifact.get("kind") or "artifact")
        artifacts_by_subtask.setdefault(subtask, []).append(f"{kind} artifact '{name}'")

    candidates: list[_Candidate] = []
    for step in steps:
        status = str(step.get("status") or "").strip().lower()
        if status in ("failed", "error", "skipped", "cancelled", "canceled"):
            continue
        summary = _step_summary(step)
        if not summary:
            continue
        title = str(step.get("title") or step.get("subtask_id") or "step").strip()
        agent = str(step.get("agent") or "agent").strip()
        subtask = str(step.get("subtask_id") or step.get("id") or "").strip()
        evidence = [f"step '{_truncate(title, 50)}' ({agent})"]
        evidence.extend(artifacts_by_subtask.get(subtask, []))
        sentences = [s for s in _sentences(summary) if _is_insight_sentence(s)]
        if not sentences and len(summary) >= 25:
            sentences = [summary]
        for sentence in sentences[:2]:  # noise cap per step
            candidates.append(_make_candidate(sentence, evidence))
    return candidates


# ---------------------------------------------------------------------------
# Stage 4: rank insights
# ---------------------------------------------------------------------------


def _rank_candidate(candidate: _Candidate) -> float:
    """Evidence-strength score: refs + numeric support + corroboration."""
    score = min(len(candidate.evidence), 3) * 1.0
    if candidate.numeric:
        score += 1.5
    if _PERCENT_IN_TEXT.search(candidate.detail):
        score += 0.5
    if len(set(candidate.evidence)) >= 2:
        score += 1.0
    if len(candidate.detail) > 120:
        score += 0.5  # specificity proxy: a fuller, richer claim
    if _HEDGES.search(candidate.detail):
        score -= 0.5
    return round(score, 2)


def _dedupe(candidates: list[_Candidate]) -> list[_Candidate]:
    """Drop near-duplicate claims (same normalized opening), keep best."""
    seen: dict[str, _Candidate] = {}
    order: list[str] = []
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9 ]", "", candidate.detail.lower())[:100]
        if key in seen:
            existing = seen[key]
            if len(candidate.evidence) > len(existing.evidence):
                seen[key] = candidate
        else:
            seen[key] = candidate
            order.append(key)
    return [seen[key] for key in order]


def _strength_for(score: float) -> Strength:
    """Map a ranking score to the pinned strength enum."""
    if score >= _HIGH_AT:
        return Strength.HIGH
    if score >= _MEDIUM_AT:
        return Strength.MEDIUM
    return Strength.LOW


# ---------------------------------------------------------------------------
# Stage 5: charts
# ---------------------------------------------------------------------------

_CHART_KINDS = ("bar", "line", "scatter", "pie")


def _chart_from_artifact(
    artifact: dict, index: int
) -> ChartSpec | None:
    """Build a validated ChartSpec from a chart artifact (None if hopeless).

    An artifact whose ``data`` carries an explicit but unpinned kind
    (anything outside bar|line|scatter|pie) is dropped — silently defaulting
    it to ``bar`` would misrepresent the producing agent. Artifacts with no
    kind at all default to ``bar``.
    """
    data = _artifact_field(artifact, "data", default=None)
    explicit_kind = ""
    if isinstance(data, dict):
        explicit_kind = str(data.get("kind") or "").strip().lower()
    spec: dict[str, Any] = {}
    if isinstance(data, dict) and explicit_kind in _CHART_KINDS:
        spec = dict(data)
    else:
        for key in ("chart", "spec", "chart_spec"):
            nested = artifact.get(key)
            if isinstance(nested, dict) and str(nested.get("kind") or "") in _CHART_KINDS:
                spec = dict(nested)
                break
    kind = str(spec.get("kind") or artifact.get("chart_kind") or explicit_kind or "bar").strip().lower()
    if kind not in _CHART_KINDS:
        return None
    points = spec.get("data")
    if points is None:
        points = data if isinstance(data, list) else []
    chart_id = str(spec.get("id") or _artifact_id(artifact, index) or f"chart_{index + 1}")
    if not chart_id.startswith("chart_") and not spec.get("id"):
        chart_id = f"chart_{chart_id}"
    title = str(
        spec.get("title") or _artifact_field(artifact, "name", "title", default="")
        or _truncate(str(_artifact_field(artifact, "summary", default="") or ""), 60)
        or f"Chart {index + 1}"
    )
    try:
        return ChartSpec(
            id=chart_id,
            kind=kind,  # type: ignore[arg-type]
            title=title,
            x_label=str(spec.get("x_label") or artifact.get("x_label") or ""),
            y_label=str(spec.get("y_label") or artifact.get("y_label") or ""),
            data=points if isinstance(points, list) else [],
            notes=str(spec.get("notes") or _artifact_field(artifact, "summary", default="") or ""),
            path=str(_artifact_field(artifact, "path", default="") or None)
            if _artifact_field(artifact, "path", default="")
            else None,
            artifact_id=_artifact_id(artifact, index),
        )
    except Exception:  # noqa: BLE001 — a bad chart must never kill the report
        return None


# ---------------------------------------------------------------------------
# Stage 6: predictions + recommendations
# ---------------------------------------------------------------------------

_CONF_IN_TEXT: re.Pattern[str] = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_CONF_DECIMAL: re.Pattern[str] = re.compile(r"\b(0\.\d+)\b")


def _confidence_from_text(text: str) -> float | None:
    """Parse a confidence out of free text ('82%', '0.82')."""
    match = _CONF_IN_TEXT.search(text or "")
    if match:
        return max(0.0, min(1.0, float(match.group(1)) / 100.0))
    match = _CONF_DECIMAL.search(text or "")
    if match:
        return max(0.0, min(1.0, float(match.group(1))))
    return None


def _prediction_from_artifact(
    artifact: dict, index: int
) -> Prediction | None:
    """Build a Prediction from a prediction artifact (claim required)."""
    name = _artifact_name(artifact, index)
    evidence = [f"prediction artifact '{name}'"]
    data = _artifact_field(artifact, "data", "payload", "prediction", default={})
    summary = str(_artifact_field(artifact, "summary", default="") or "").strip()
    claim = ""
    confidence: Any = None
    basis = ""
    if isinstance(data, dict):
        claim = str(data.get("claim") or data.get("title") or "").strip()
        confidence = data.get("confidence", data.get("probability"))
        basis = str(data.get("basis") or data.get("rationale") or "").strip()
    if not claim:
        claim = summary
    if not claim:
        return None
    if confidence is None:
        confidence = _confidence_from_text(f"{summary} {basis}")
    flags: list[str] = []
    if confidence is None:
        confidence = 0.5
        flags.append("confidence_assumed")
    if not basis:
        basis = f"Derived from {name} and the underlying run artifacts."
        flags.append("basis_derived")
    try:
        return Prediction(
            claim=claim, confidence=confidence, basis=basis,
            evidence=evidence, flags=flags,
        )
    except Exception:  # noqa: BLE001
        return None


def _prediction_from_forecaster_step(step: dict) -> Prediction | None:
    """Fallback prediction from a forecaster step output (no artifact)."""
    if str(step.get("agent") or "").strip().lower() != "forecaster":
        return None
    summary = _step_summary(step)
    if not summary:
        return None
    title = str(step.get("title") or "forecast").strip()
    confidence = _confidence_from_text(summary) or 0.5
    flags = [] if _confidence_from_text(summary) is not None else ["confidence_assumed"]
    return Prediction(
        claim=_truncate(summary, 240),
        confidence=confidence,
        basis=f"Forecast produced by the forecaster agent during step '{title}'.",
        evidence=[f"step '{_truncate(title, 50)}' (forecaster)"],
        flags=flags,
    )


def _impact_score(rec_like: dict) -> int:
    """Impact 1-3 from explicit field or the expected_impact wording."""
    explicit = str(rec_like.get("impact") or rec_like.get("impact_level") or "").strip().lower()
    if explicit in ("high", "h", "3"):
        return 3
    if explicit in ("medium", "med", "m", "2"):
        return 2
    if explicit in ("low", "l", "1"):
        return 1
    text = str(rec_like.get("expected_impact") or rec_like.get("impact_text") or "")
    if _IMPACT_HIGH.search(text):
        return 3
    if _IMPACT_MEDIUM.search(text):
        return 2
    return 1


def _recommendation_from_artifact(
    artifact: dict, index: int
) -> Recommendation | None:
    """Build a Recommendation from a recommendation artifact."""
    name = _artifact_name(artifact, index)
    evidence = [f"recommendation artifact '{name}'"]
    data = _artifact_field(artifact, "data", "payload", "recommendation", default={})
    summary = str(_artifact_field(artifact, "summary", default="") or "").strip()
    title = ""
    action = ""
    impact = ""
    effort = "M"
    if isinstance(data, dict):
        title = str(data.get("title") or data.get("name") or "").strip()
        action = str(data.get("action") or data.get("detail") or "").strip()
        impact = str(data.get("expected_impact") or data.get("impact") or "").strip()
        effort = str(data.get("effort") or "M").strip()
    if not title:
        title = _artifact_field(artifact, "name", "title", default="") or _truncate(summary, 60)
    title = str(title).strip() or f"Recommendation {index + 1}"
    if not action:
        action = summary or title
    try:
        return Recommendation(
            title=title, action=action, expected_impact=impact,
            effort=effort, evidence=evidence,
        )
    except Exception:  # noqa: BLE001
        return None


def _assign_priorities(recs: list[Recommendation], impacts: list[int]) -> None:
    """Rank by impact/effort matrix and write priority 1..n (clamped to 5)."""
    order = sorted(
        range(len(recs)),
        key=lambda i: (-(impacts[i] * 2 - recs[i].effort.cost), i),
    )
    for rank, index in enumerate(order, start=1):
        recs[index].priority = min(rank, 5)
    recs.sort(key=lambda r: r.priority)


# ---------------------------------------------------------------------------
# Executive summary + appendix
# ---------------------------------------------------------------------------


def _status_sentence(ctx: _ParsedRun) -> str:
    """Honest run-status sentence for the executive summary."""
    steps_total = len(ctx.steps)
    steps_done = sum(
        1 for s in ctx.steps if str(s.get("status") or "").lower() in ("completed", "succeeded", "done")
    )
    if ctx.status == "succeeded":
        base = "The agent team completed the run successfully."
    elif ctx.status == "partial":
        base = (
            f"The run finished partially: {steps_done} of {steps_total} steps "
            "completed; the findings below cover only the completed work."
        )
    elif ctx.status == "failed":
        base = (
            "The run FAILED before completing; the material below reflects "
            "only partial work and should be treated with caution."
        )
    else:
        base = f"Run status: {ctx.status}."
    if ctx.errors:
        base += f" Recorded errors: {ctx.errors[0]}"
        if len(ctx.errors) > 1:
            base += f" (+{len(ctx.errors) - 1} more, see appendix)"
        base += "."
    return base


def _insight_block(report_insights: list, profile: StyleProfile) -> str:
    """Executive-summary sentences about the top insights (flagged excluded)."""
    usable = [
        i for i in report_insights
        if "unsupported_claim" not in i.flags and i.strength != Strength.LOW
    ]
    if not usable:
        if report_insights:
            return (
                "The critic checklist flagged every candidate insight as "
                "insufficiently supported; the downgraded claims are listed in "
                "the insights section without endorsement."
            )
        return ""
    count = len(usable)
    vocab = profile.summary_vocabulary
    top = usable[0]
    extra = usable[1:profile.exec_summary_max_insights]
    text = (
        f"The team surfaced {count} key {vocab}{'s' if count != 1 else ''}. "
        f"Most notably: {top.detail.rstrip('.')}."
    )
    if extra:
        titles = " and ".join(_truncate(e.title.rstrip('.'), 60) for e in extra)
        text += f" Also notable: {titles}."
    return text


def _prediction_block(predictions: list) -> str:
    """Executive-summary sentence about forecasts."""
    if not predictions:
        return ""
    top = max(predictions, key=lambda p: p.confidence)
    pct = int(round(top.confidence * 100))
    return (
        f"The forecaster issued {len(predictions)} prediction"
        f"{'s' if len(predictions) != 1 else ''} with confidence up to {pct}% "
        f"(top claim: {_truncate(top.claim.rstrip('.'), 90)})."
    )


def _recommendation_block(recommendations: list, profile: StyleProfile) -> str:
    """Executive-summary sentence about the top-ranked actions."""
    if not recommendations:
        return ""
    first = recommendations[0]
    more = recommendations[1:profile.top_n_recommendations]
    text = (
        f"Top recommendation (priority {first.priority}): "
        f"{_truncate(first.action.rstrip('.') or first.title, 110)}"
    )
    if first.expected_impact:
        text += f" — expected impact: {_truncate(first.expected_impact.rstrip('.'), 80)}"
    text += f" (effort: {first.effort.value})."
    if more:
        titles = " and ".join(_truncate(r.title.rstrip('.'), 50) for r in more)
        text += f" Next up: {titles}."
    return text


def _chart_block(charts: list) -> str:
    """Executive-summary sentence about supporting charts."""
    if not charts:
        return ""
    titles = ", ".join(c.title for c in charts[:3] if c.title)
    plural = len(charts) != 1
    return (
        f"{len(charts)} supporting chart{'s' if plural else ''} ({titles}) "
        f"{'are' if plural else 'is'} included below."
    )


def _compose_summary(
    ctx: _ParsedRun, report, profile: StyleProfile, artifacts_total: int
) -> str:
    """Deterministic executive summary; block order follows style emphasis."""
    parts: list[str] = [
        f'This report answers the mission: "{ctx.mission}".',
    ]
    if artifacts_total == 0:
        parts.append(_status_sentence(ctx))
        parts.append(
            "No artifacts were produced during this run, so there is no "
            "evidence to report — this is an honest empty result. Re-run the "
            "mission with a dataset attached, or verify that the worker "
            "agents (researcher, analyst, forecaster) are enabled."
        )
        return " ".join(p for p in parts if p)
    blocks: dict[str, str] = {
        "insights": _insight_block(report.insights, profile),
        "predictions": _prediction_block(report.predictions),
        "recommendations": _recommendation_block(report.recommendations, profile),
    }
    parts.append(_status_sentence(ctx))
    lead = profile.exec_summary_emphasis
    if lead in blocks:
        if blocks[lead]:
            parts.append(blocks.pop(lead))
    for key in ("insights", "predictions", "recommendations"):
        if blocks.get(key):
            parts.append(blocks.pop(key))
    chart_sentence = _chart_block(report.charts)
    if chart_sentence:
        parts.append(chart_sentence)
    return " ".join(p for p in parts if p)


def _fmt_int(value: Any) -> str:
    """Format an optional int with thousands separators."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value) if value is not None else "0"


def _fmt_cost(value: Any) -> str:
    """Format an optional USD cost defensively."""
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return "$0.0000"


def _compose_appendix(
    ctx: _ParsedRun,
    profile: StyleProfile,
    artifacts_by_kind: dict[str, list[tuple[int, dict]]],
    stats: dict[str, int],
    issues: list[str],
) -> str:
    """Markdown appendix: run details, plan, token usage, errors, coverage."""
    lines: list[str] = []

    lines.append("### Run details")
    steps_total = len(ctx.steps)
    steps_done = sum(
        1 for s in ctx.steps if str(s.get("status") or "").lower() in ("completed", "succeeded", "done")
    )
    lines.append(f"- **Mission:** {ctx.mission}")
    lines.append(f"- **Run status:** {ctx.status} ({steps_done}/{steps_total} steps completed)")
    if ctx.run_id:
        lines.append(f"- **Run id:** `{ctx.run_id}`")
    lines.append(f"- **Style:** {profile.display_name} (`{profile.name}`)")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append(
        f"- **Generated:** {generated} by orchestrator.report v{_PIPELINE_VERSION} "
        "(deterministic mode, no LLM calls)"
    )

    lines.append("")
    lines.append("### Plan")
    if ctx.plan:
        for i, subtask in enumerate(ctx.plan, start=1):
            title = str(subtask.get("title") or subtask.get("id") or f"subtask {i}")
            agent = str(subtask.get("agent") or "unassigned")
            status = str(subtask.get("status") or "unknown")
            lines.append(f"{i}. {title} — *{agent}* ({status})")
    else:
        lines.append("No plan was recorded for this run.")

    lines.append("")
    lines.append("### Token usage")
    usage = ctx.token_usage or {}
    totals = usage.get("totals") if isinstance(usage.get("totals"), dict) else {}
    per_agent = usage.get("per_agent") if isinstance(usage.get("per_agent"), dict) else {}
    if totals or per_agent:
        if totals:
            lines.append(
                f"- **Total:** {_fmt_int(totals.get('input_tokens'))} input / "
                f"{_fmt_int(totals.get('output_tokens'))} output — "
                f"{_fmt_cost(totals.get('cost_usd'))}"
            )
        for role, role_usage in per_agent.items():
            if not isinstance(role_usage, dict):
                continue
            lines.append(
                f"- {role}: {_fmt_int(role_usage.get('input_tokens'))} input / "
                f"{_fmt_int(role_usage.get('output_tokens'))} output — "
                f"{_fmt_cost(role_usage.get('cost_usd'))}"
            )
    else:
        lines.append("No token usage was recorded for this run.")

    lines.append("")
    lines.append("### Errors")
    if ctx.errors:
        for error in ctx.errors:
            lines.append(f"- {error}")
    else:
        lines.append("No errors recorded.")

    lines.append("")
    lines.append("### Data coverage notes")
    kind_counts = ", ".join(
        f"{len(items)} {kind}" for kind, items in sorted(artifacts_by_kind.items())
    )
    lines.append(
        f"- {stats['artifacts_total']} artifact(s) collected"
        f"{f': {kind_counts}' if kind_counts else ' (none)'}"
    )
    lines.append(
        f"- {stats['insight_candidates']} candidate insight(s) extracted; "
        f"{stats['insights_kept']} kept after ranking and critic review."
    )
    if stats.get("charts_dropped"):
        lines.append(f"- {stats['charts_dropped']} invalid/empty chart(s) dropped.")
    missing = [
        section
        for section in profile.required_sections
        if not stats.get(f"section_{section}")
    ]
    if missing:
        lines.append(
            f"- Required sections for style `{profile.name}` came out empty: "
            + ", ".join(missing)
            + " (reported honestly rather than faked)."
        )
    if issues:
        lines.append(f"- Critic checklist raised {len(issues)} issue(s); see report meta.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Optional LLM polish (never on the tested/default path)
# ---------------------------------------------------------------------------


def _llm_polish_summary(summary: str, mission: str) -> tuple[str, bool]:
    """Polish the exec summary via orchestrator.llm when live mode allows it.

    Returns ``(text, polished)``. Any import/API failure silently falls back
    to the deterministic summary — the report must never depend on the LLM.
    """
    if os.environ.get("LLM_MODE", "mock").strip().lower() != "live":
        return summary, False
    try:  # pragma: no cover - exercised only with a live orchestrator core
        from orchestrator.llm import get_llm  # type: ignore
    except Exception:
        return summary, False
    try:  # pragma: no cover - depends on Agent 3's LLM API surface
        llm = get_llm()
        prompt = (
            "Rewrite the following executive summary of a business-analysis "
            "report in clearer, tighter prose. Keep every number, claim and "
            "hedging exactly as-is; do not add new claims. "
            f'Mission: "{mission}".\n\nSummary:\n{summary}'
        )
        output: Any = None
        for method_name in ("complete", "generate", "chat", "ask"):
            method = getattr(llm, method_name, None)
            if callable(method):
                output = method(prompt)
                break
        if output is None:
            return summary, False
        if isinstance(output, dict):
            output = output.get("text") or output.get("content") or output.get("message") or ""
        polished = str(output).strip()
        if len(polished) < 40:
            return summary, False
        return polished, True
    except Exception:
        return summary, False


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def build_report(run_result: dict, style: str = "default") -> dict:
    """Build the pinned report dict from a finished run.

    Args:
        run_result: ``RunResult.to_dict()`` shape:
            ``{run_id?, mission, status, plan, steps, artifacts, token_usage,
            errors}``. Missing keys are tolerated.
        style: One of ``default|market_research|sales_insights|support_triage``.
            Unknown styles fall back to ``default`` (recorded in meta).

    Returns:
        JSON-safe dict matching the pinned Report model in
        ``docs/INTERFACES.md`` (plus additive ``meta`` diagnostics).

    Raises:
        TypeError: if ``run_result`` is not a dict.
    """
    ctx = _parse_run(run_result)
    requested_style = style
    profile = get_style(style)

    # Stage 2: collect.
    grouped = _collect_artifacts(ctx.artifacts)
    artifacts_total = sum(len(items) for items in grouped.values())

    # Stages 3-4: extract + rank insights.
    candidates = _extract_from_artifacts(grouped) + _extract_from_steps(ctx.steps, grouped)
    candidates = _dedupe(candidates)
    for candidate in candidates:
        candidate.score = _rank_candidate(candidate)
    candidates.sort(key=lambda c: (-c.score, -len(c.evidence), c.title))
    candidates = candidates[: profile.max_insights]

    # Stage 5: charts.
    charts: list[ChartSpec] = []
    charts_dropped = 0
    for index, artifact in grouped.get("chart", []):
        chart = _chart_from_artifact(artifact, index)
        if chart is None:
            charts_dropped += 1
            continue
        charts.append(chart)

    # Stage 6: predictions.
    predictions: list[Prediction] = []
    for index, artifact in grouped.get("prediction", []):
        prediction = _prediction_from_artifact(artifact, index)
        if prediction is not None:
            predictions.append(prediction)
    if not predictions:
        for step in ctx.steps:
            prediction = _prediction_from_forecaster_step(step)
            if prediction is not None:
                predictions.append(prediction)
    predictions = predictions[: profile.max_predictions]

    # Stage 6: recommendations.
    recommendations: list[Recommendation] = []
    for index, artifact in grouped.get("recommendation", []):
        rec = _recommendation_from_artifact(artifact, index)
        if rec is not None:
            recommendations.append(rec)
    impacts = [_impact_score({"expected_impact": rec.expected_impact}) for rec in recommendations]
    _assign_priorities(recommendations, impacts)
    recommendations = recommendations[: profile.max_recommendations]
    recommendations.sort(key=lambda r: r.priority)

    # Stage 7: critic checklist (reject unsupported claims BEFORE summarizing).
    report = Report(
        title=f"AgentForge Report: {_truncate(ctx.mission, 80)}" if ctx.mission else "AgentForge Report",
        mission=ctx.mission,
        style=profile.name,
        insights=[],
        charts=charts,
        predictions=predictions,
        recommendations=recommendations,
    )
    for rank, candidate in enumerate(candidates, start=1):
        report.insights.append(
            Insight(
                title=candidate.title,
                detail=candidate.detail,
                evidence=candidate.evidence,
                strength=_strength_for(candidate.score),
                score=candidate.score,
                rank=rank,
            )
        )
    report, issues = run_critic_checklist(report)

    # Stage 8: deterministic executive summary (post-scrub), optional polish.
    summary = _compose_summary(ctx, report, profile, artifacts_total)
    summary, polished = _llm_polish_summary(summary, ctx.mission)
    report.executive_summary = summary

    # Stage 9: appendix.
    stats = {
        "artifacts_total": artifacts_total,
        "insight_candidates": len(candidates),
        "insights_kept": len(report.insights),
        "charts_kept": len(report.charts),
        "charts_dropped": charts_dropped,
        "predictions_kept": len(report.predictions),
        "recommendations_kept": len(report.recommendations),
        "steps_total": len(ctx.steps),
    }
    for section in ("insights", "charts", "predictions", "recommendations"):
        stats[f"section_{section}"] = len(getattr(report, section))
    report.appendix = _compose_appendix(ctx, profile, grouped, stats, issues)

    normalized_style = str(requested_style).strip().lower()
    if normalized_style.endswith("_team"):
        normalized_style = normalized_style[: -len("_team")]
    report.meta = {
        "pipeline_version": _PIPELINE_VERSION,
        "run_id": ctx.run_id,
        "run_status": ctx.status,
        "requested_style": requested_style,
        # A trailing _team suffix (marketplace template id) maps cleanly to a
        # style profile, so it does not count as a fallback.
        "style_fallback": profile.name != normalized_style,
        "style_profile": profile.display_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "token_usage": ctx.token_usage,
        "critic_issues": issues,
        "critic_clean": not issues,
        "llm_polished": polished,
        "stats": stats,
    }
    return report.model_dump(mode="json")
