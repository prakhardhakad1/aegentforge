"""Chart rendering: pinned ChartSpec -> PNG via matplotlib (Agg backend).

A ``ChartSpec`` is the pinned tools -> report -> frontend contract from
``docs/INTERFACES.md``::

    {"id": "chart_1", "kind": "bar|line|scatter|pie", "title": "...",
     "x_label": "...", "y_label": "...",
     "data": [{"label": "...", "x": 123, "y": 456}], "notes": "..."}

``render_chart_spec(spec, out_dir)`` is the shared helper used by the report
pipeline; :class:`ChartTool` wraps it as a Tool that writes into the run
workspace. ``MPLBACKEND`` is forced to ``Agg`` before pyplot is imported so
this module never touches a display (Windows dev boxes and CI alike).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib  # noqa: E402  (import after MPLBACKEND default is set)

matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from agentforge_tools.base import Tool, ToolResult  # noqa: E402

__all__ = ["ChartTool", "render_chart_spec", "CHART_KINDS", "validate_chart_spec"]

CHART_KINDS = ("bar", "line", "scatter", "pie")

_MAX_POINTS = 500          # per-series point cap for rendering sanity
_MAX_PIE_SLICES = 10       # beyond this, smallest slices fold into "other"
_FIG_DPI = 150
_ID_SANITIZE = re.compile(r"[^A-Za-z0-9_.-]+")


def validate_chart_spec(spec: Any) -> dict:
    """Validate a ChartSpec dict and normalize it; raise ``ValueError`` if bad.

    Returns the same dict (unchanged) when valid. Checks: dict shape, allowed
    ``kind``, non-empty ``data`` list, and that every entry's ``y`` is numeric.
    """
    if not isinstance(spec, dict):
        raise ValueError(f"chart spec must be a dict, got {type(spec).__name__}")
    kind = spec.get("kind")
    if kind not in CHART_KINDS:
        raise ValueError(f"chart kind must be one of {CHART_KINDS}, got {kind!r}")
    data = spec.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("chart spec must include a non-empty 'data' list")
    for i, point in enumerate(data):
        if not isinstance(point, dict):
            raise ValueError(f"data[{i}] must be a dict, got {type(point).__name__}")
        y = point.get("y")
        if isinstance(y, bool) or not isinstance(y, (int, float)):
            raise ValueError(f"data[{i}].y must be numeric, got {y!r}")
    return spec


def _sanitize_filename_stem(spec_id: Any) -> str:
    """Map a spec id to a safe filename stem."""
    stem = _ID_SANITIZE.sub("_", str(spec_id)).strip("._")
    return stem or "chart"


def _coerce_points(spec: dict) -> list[tuple[str, float | str, float]]:
    """Normalize data points into (label, x, y) tuples with numeric y."""
    points: list[tuple[str, float | str, float]] = []
    for i, point in enumerate(spec["data"][:_MAX_POINTS]):
        label_raw = point.get("label")
        label = "" if label_raw is None else str(label_raw)
        x_raw = point.get("x")
        if isinstance(x_raw, bool):
            x: float | str = float(x_raw)
        elif isinstance(x_raw, (int, float)):
            x = float(x_raw)
        else:
            x = "" if x_raw is None else str(x_raw)
        y = float(point["y"])  # validate_chart_spec guarantees numeric
        points.append((label, x, y))
    return points


def _x_positions(xs: list[float | str]) -> tuple[list[float], list[str] | None]:
    """Turn x values into numeric positions plus optional tick labels.

    Numeric x values are used directly; anything else is plotted by position
    with the original values (stringified) as tick labels.
    """
    if xs and all(isinstance(x, float) for x in xs):
        return xs, None
    positions = list(range(len(xs)))
    labels = [str(x) for x in xs]
    return [float(p) for p in positions], labels


def _style_ticks(labels: list[str]) -> None:
    """Rotate tick labels when they are long or numerous."""
    if len(labels) > 8 or any(len(label) > 12 for label in labels):
        plt.xticks(rotation=35, ha="right", fontsize=8)
    else:
        plt.xticks(fontsize=8)


def render_chart_spec(spec: dict, out_dir: str | Path) -> Path:
    """Render a pinned ``ChartSpec`` to ``<out_dir>/<id>.png`` and return it.

    Args:
        spec: ChartSpec dict (see module docstring). ``y`` values must be
            numeric; ``x`` may be numeric or string (string x is plotted by
            position with tick labels).
        out_dir: Directory the PNG is written to (created if missing).

    Returns:
        Absolute :class:`~pathlib.Path` of the written PNG.

    Raises:
        ValueError: If the spec is invalid (wrong kind, empty data,
            non-numeric y, non-numeric x for scatter, ...) or a pie chart has
            no positive values to plot.
        OSError: If the PNG cannot be written.
    """
    validate_chart_spec(spec)
    points = _coerce_points(spec)
    kind: str = spec["kind"]
    title = str(spec.get("title") or "")
    x_label = str(spec.get("x_label") or "")
    y_label = str(spec.get("y_label") or "")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / f"{_sanitize_filename_stem(spec.get('id'))}.png"

    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    try:
        if kind == "bar":
            labels = [p[0] or p[1] for p in points]
            positions, tick_labels = _x_positions([p[1] for p in points])
            ys = [p[2] for p in points]
            if tick_labels is not None and not any(label for label in tick_labels):
                tick_labels = [str(label) for label in labels]
            ax.bar(positions, ys, color="#4C78A8", edgecolor="none")
            if tick_labels is not None:
                ax.set_xticks(positions)
                ax.set_xticklabels(tick_labels)
                _style_ticks(tick_labels)
            ax.grid(axis="y", alpha=0.3)

        elif kind == "line":
            positions, tick_labels = _x_positions([p[1] for p in points])
            ys = [p[2] for p in points]
            ax.plot(positions, ys, color="#4C78A8", linewidth=1.8, marker="o", markersize=3)
            if tick_labels is not None:
                ax.set_xticks(positions[:: max(1, len(positions) // 12)])
                ax.set_xticklabels(tick_labels[:: max(1, len(tick_labels) // 12)])
                _style_ticks(tick_labels)
            ax.grid(alpha=0.3)

        elif kind == "scatter":
            try:
                xs = [float(p[1]) for p in points]
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "scatter charts require numeric x values in every data point"
                ) from exc
            ys = [p[2] for p in points]
            ax.scatter(xs, ys, s=18, color="#4C78A8", alpha=0.75, edgecolors="none")
            ax.grid(alpha=0.3)

        else:  # pie
            labeled = [p for p in points if p[2] > 0]
            if not labeled:
                raise ValueError("pie chart requires at least one positive y value")
            labeled = sorted(labeled, key=lambda p: p[2], reverse=True)
            if len(labeled) > _MAX_PIE_SLICES:
                kept, rest = labeled[: _MAX_PIE_SLICES - 1], labeled[_MAX_PIE_SLICES - 1:]
                labeled = kept + [(f"other ({len(rest)})", "", sum(p[2] for p in rest))]
            labels = [p[0] or f"item_{i + 1}" for i, p in enumerate(labeled)]
            sizes = [p[2] for p in labeled]
            ax.pie(
                sizes,
                labels=labels,
                autopct="%1.1f%%",
                textprops={"fontsize": 8},
                startangle=90,
                counterclock=False,
            )
            ax.set_aspect("equal")

        ax.set_title(title, fontsize=11)
        ax.set_xlabel(x_label, fontsize=9)
        ax.set_ylabel(y_label, fontsize=9)
        fig.tight_layout()
        fig.savefig(file_path, dpi=_FIG_DPI, format="png")
    finally:
        plt.close(fig)

    return file_path.resolve()


class ChartTool(Tool):
    """Tool: render a pinned ChartSpec into the workspace as a PNG artifact."""

    name = "chart"
    description = (
        "Render a chart from a ChartSpec (kind: bar|line|scatter|pie; data: "
        "[{label, x, y}] with numeric y) into a PNG file in the run workspace. "
        "Use after csv_analyzer to visualize a finding; the report embeds "
        "charts by chart id."
    )
    parameters_json_schema = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "description": (
                    "ChartSpec: {id, kind: bar|line|scatter|pie, title, "
                    "x_label, y_label, data: [{label, x, y}], notes}."
                ),
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique chart id, e.g. 'chart_1'.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["bar", "line", "scatter", "pie"],
                        "description": "Chart type.",
                    },
                    "title": {"type": "string", "description": "Chart title."},
                    "x_label": {"type": "string", "description": "X axis label."},
                    "y_label": {"type": "string", "description": "Y axis label."},
                    "data": {
                        "type": "array",
                        "description": "Data points; y must be numeric.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "x": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                                "y": {"type": "number"},
                            },
                            "required": ["y"],
                        },
                    },
                    "notes": {"type": "string", "description": "How to read this chart."},
                },
                "required": ["kind", "data"],
            },
        },
        "required": ["spec"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_dir: str | Path) -> None:
        """Create the chart tool writing into ``<workspace_dir>/charts``."""
        self._workspace = Path(workspace_dir).resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)

    @property
    def workspace(self) -> Path:
        """The resolved workspace root."""
        return self._workspace

    def run(self, inputs: dict) -> ToolResult:
        """Render ``inputs['spec']`` to a PNG. Never raises."""
        spec = inputs.get("spec")
        out_dir = self._workspace / "charts"
        try:
            path = render_chart_spec(spec, out_dir)
        except Exception as exc:  # noqa: BLE001 - uniform tool contract: run() never raises
            return ToolResult(
                ok=False,
                error=f"chart rendering failed: {type(exc).__name__}: {exc}",
            )
        artifact = {"name": path.name, "path": str(path), "kind": "chart"}
        return ToolResult(
            ok=True,
            data={
                "name": path.name,
                "path": str(path),
                "chart_id": str(spec.get("id") or path.stem) if isinstance(spec, dict) else path.stem,
            },
            artifacts=[artifact],
        )
