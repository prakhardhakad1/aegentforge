"""Pydantic models for the AgentForge report pipeline (Agent 6).

These models encode the pinned Report contract from ``docs/INTERFACES.md``:

    {
      "title": "...", "mission": "...", "style": "default|...",
      "executive_summary": "...",
      "insights": [{"title","detail","evidence": ["..."],"strength": "high|medium|low"}],
      "charts": [ /* ChartSpec */ ],
      "predictions": [{"claim","confidence": 0.87,"basis": "..."}],
      "recommendations": [{"title","action","expected_impact","effort": "S|M|L","priority": 1}],
      "appendix": "..."
    }

``priority`` 1 = do first. Everything here is pure stdlib + pydantic; the report
subpackage never imports orchestrator core modules at import time.

Only fields defined in the pinned contract are required; a few additive,
optional fields (``flags``, ``score``, ``path`` ...) exist so the ranking and
critic checklist can carry provenance without breaking consumers that only
read the pinned keys.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "Strength",
    "Effort",
    "Insight",
    "Prediction",
    "Recommendation",
    "ChartSpec",
    "Report",
    "coerce_report",
]

VALID_CHART_KINDS: tuple[str, ...] = ("bar", "line", "scatter", "pie")
"""Chart kinds pinned in docs/INTERFACES.md (``chart`` artifacts excluded)."""


class Strength(str, Enum):
    """Evidence strength of an insight (pinned values)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def weight(self) -> int:
        """Numeric weight for ranking (higher is stronger)."""
        return {"high": 3, "medium": 2, "low": 1}[self.value]


class Effort(str, Enum):
    """Implementation effort of a recommendation (pinned values)."""

    S = "S"
    M = "M"
    L = "L"

    @property
    def cost(self) -> int:
        """Numeric cost for the priority matrix (higher means more effort)."""
        return {"S": 0, "M": 1, "L": 2}[self.value]


class Insight(BaseModel):
    """One evidence-backed finding. ``strength`` is computed by ranking."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    title: str = Field(..., min_length=1, description="Short claim headline.")
    detail: str = Field("", description="Full claim text, one or two sentences.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Human-readable evidence references (artifact/step citations).",
    )
    strength: Strength = Field(default=Strength.LOW, description="high|medium|low.")
    flags: list[str] = Field(
        default_factory=list,
        description="Critic flags, e.g. 'unsupported_claim', 'absolute_claim'.",
    )
    score: float | None = Field(
        default=None, description="Raw ranking score (diagnostic, not pinned)."
    )
    rank: int | None = Field(
        default=None, description="1-based rank after sorting (diagnostic)."
    )

    @field_validator("title", "detail", mode="before")
    @classmethod
    def _coerce_str(cls, value: Any) -> str:
        """Coerce non-string input (numbers, dicts) to a readable string."""
        if value is None:
            return ""
        if isinstance(value, dict):
            return " ".join(str(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return " ".join(str(v) for v in value)
        return str(value)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        """A blank title makes the insight unusable; fall back to detail text."""
        cleaned = value.strip()
        return cleaned if cleaned else "(untitled insight)"

    @field_validator("evidence", "flags", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: Any) -> list[str]:
        """Accept a bare string or a list of arbitrary scalars."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, (list, tuple)):
            out: list[str] = []
            for item in value:
                text = str(item).strip() if item is not None else ""
                if text:
                    out.append(text)
            return out
        return [str(value)]

    @field_validator("strength", mode="before")
    @classmethod
    def _coerce_strength(cls, value: Any) -> Any:
        """Accept 'HIGH'/'High' and map unknown values to low."""
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("high", "medium", "low"):
                return lowered
            return "low"
        return value


class Prediction(BaseModel):
    """A forward-looking claim with an explicit confidence and basis."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    claim: str = Field(..., min_length=1, description="What we predict will happen.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Calibrated confidence in [0, 1]."
    )
    basis: str = Field("", description="Why: the data/evidence behind the claim.")
    evidence: list[str] = Field(
        default_factory=list, description="Artifact/step citations (additive)."
    )
    flags: list[str] = Field(default_factory=list, description="Critic flags.")

    @field_validator("claim", mode="before")
    @classmethod
    def _coerce_claim(cls, value: Any) -> str:
        """Coerce arbitrary input to a claim string."""
        if value is None:
            return "(unspecified prediction)"
        if isinstance(value, dict):
            return " ".join(str(v) for v in value.values()) or "(unspecified prediction)"
        return str(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> Any:
        """Accept '82%' / '0.82' / '82' percent-style strings and clamp."""
        if isinstance(value, str):
            text = value.strip().rstrip("%")
            try:
                number = float(text)
            except ValueError:
                return 0.5
            if value.strip().endswith("%") or number > 1.0:
                number = number / 100.0
            return number
        if isinstance(value, bool) or value is None:
            return 0.5
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                return 0.5
            if number > 1.0:
                # >1.0 is read as a percentage (87 -> 0.87); near-1 values on a
                # sloppy 0-1 scale (e.g. 1.5) are clamped instead of divided.
                number = number / 100.0 if number > 1.5 else min(number, 1.0)
            return max(0.0, min(1.0, number))
        return value

    @field_validator("basis", "evidence", "flags", mode="before")
    @classmethod
    def _coerce_str_fields(cls, value: Any) -> Any:
        """Delegate string/list coercion (basis stays a string here)."""
        if value is None:
            return "" if isinstance(value, str) or value is None else []
        return value


class Recommendation(BaseModel):
    """A ranked action. ``priority`` 1 = do first (impact/effort matrix)."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    title: str = Field(..., min_length=1, description="Short action headline.")
    action: str = Field("", description="Concrete thing to do.")
    expected_impact: str = Field("", description="Expected business impact.")
    effort: Effort = Field(default=Effort.M, description="S|M|L.")
    priority: int = Field(default=3, ge=1, le=5, description="1 = do first.")
    evidence: list[str] = Field(
        default_factory=list, description="Artifact/step citations (additive)."
    )
    flags: list[str] = Field(default_factory=list, description="Critic flags.")

    @field_validator("title", "action", "expected_impact", mode="before")
    @classmethod
    def _coerce_str(cls, value: Any) -> str:
        """Coerce non-string input to a readable string."""
        if value is None:
            return ""
        if isinstance(value, dict):
            return " ".join(str(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return " ".join(str(v) for v in value)
        return str(value)

    @field_validator("effort", mode="before")
    @classmethod
    def _coerce_effort(cls, value: Any) -> Any:
        """Accept 's'/'small'/'S' and map unknown values to M."""
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("s", "small", "low"):
                return "S"
            if lowered in ("m", "medium", "mid"):
                return "M"
            if lowered in ("l", "large", "big", "high"):
                return "L"
            return "M"
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _coerce_priority(cls, value: Any) -> Any:
        """Clamp priorities outside 1..5 instead of rejecting the report."""
        try:
            number = int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 3
        return max(1, min(5, number))


class ChartSpec(BaseModel):
    """Pinned ChartSpec (passthrough) with optional artifact provenance."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    id: str = Field(..., min_length=1, description="Stable chart id, e.g. 'chart_1'.")
    kind: Literal["bar", "line", "scatter", "pie"] = Field(
        ..., description="Chart type pinned in docs/INTERFACES.md."
    )
    title: str = Field("", description="Human-readable chart title.")
    x_label: str = Field("", description="X axis label.")
    y_label: str = Field("", description="Y axis label.")
    data: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Points shaped {label, x, y}; passthrough dicts.",
    )
    notes: str = Field("", description="Optional footnote.")
    path: str | None = Field(
        default=None, description="Rendered image path on disk (additive, optional)."
    )
    artifact_id: str | None = Field(
        default=None, description="Originating artifact id (additive, optional)."
    )

    @field_validator("id", "title", "x_label", "y_label", "notes", mode="before")
    @classmethod
    def _coerce_str(cls, value: Any) -> str:
        """Coerce scalars to strings; blank id gets a placeholder."""
        if value is None:
            return ""
        return str(value)

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_points(cls, value: Any) -> list[dict[str, Any]]:
        """Keep dict points, map list/tuple points positionally, drop junk."""
        if value is None:
            return []
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return []
        points: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                points.append(dict(item))
            elif isinstance(item, (list, tuple)) and item:
                mapped: dict[str, Any] = {}
                if len(item) >= 1:
                    mapped["label"] = item[0]
                if len(item) >= 2:
                    mapped["x"] = item[1]
                if len(item) >= 3:
                    mapped["y"] = item[2]
                points.append(mapped)
            else:
                points.append({"label": str(item)})
        return points

    @field_validator("id")
    @classmethod
    def _id_not_blank(cls, value: str) -> str:
        """ChartSpec requires a non-empty id for frontend references."""
        return value.strip() if value.strip() else "chart_unknown"


class Report(BaseModel):
    """The pinned deliverable produced by :func:`orchestrator.report.build_report`."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    title: str = Field(..., min_length=1, description="Report title.")
    mission: str = Field("", description="The user's original mission statement.")
    style: str = Field(
        "default",
        description="default|market_research|sales_insights|support_triage",
    )
    executive_summary: str = Field("", description="Deterministic template synthesis.")
    insights: list[Insight] = Field(
        default_factory=list, description="Ranked insights, strongest first."
    )
    charts: list[ChartSpec] = Field(default_factory=list, description="Validated ChartSpecs.")
    predictions: list[Prediction] = Field(default_factory=list, description="Forecasts.")
    recommendations: list[Recommendation] = Field(
        default_factory=list, description="Priority-ordered actions (1 = do first)."
    )
    appendix: str = Field("", description="Markdown appendix: run details, tokens, errors.")
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Additive diagnostics: run_id, status, issues, token_usage, ...",
    )

    @field_validator("title", mode="before")
    @classmethod
    def _coerce_title(cls, value: Any) -> str:
        """Never allow a blank title (renderers and PDF need one)."""
        text = str(value) if value is not None else ""
        return text.strip() if text.strip() else "AgentForge Report"

    @field_validator("style", mode="before")
    @classmethod
    def _coerce_style(cls, value: Any) -> str:
        """Lowercase style ids; unknown ids are handled by the style registry."""
        return str(value).strip().lower() if value else "default"

    @field_validator("insights", "charts", "predictions", "recommendations", mode="before")
    @classmethod
    def _coerce_sections(cls, value: Any) -> list[Any]:
        """Accept None / bare dicts / lists for every section."""
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, (list, tuple)):
            return list(value)
        return []


def coerce_report(source: "Report | dict[str, Any]") -> Report:
    """Coerce a dict (or Report) into a validated :class:`Report`.

    Raises:
        ValueError: if ``source`` is neither a Report nor a dict-shaped report.
    """
    if isinstance(source, Report):
        return source
    if isinstance(source, dict):
        return Report.model_validate(source)
    raise ValueError(
        f"Expected a Report model or a report dict, got {type(source).__name__}"
    )
