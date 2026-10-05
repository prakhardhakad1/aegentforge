"""CSVAnalyzerTool: pandas-powered descriptive analysis of a CSV dataset.

Given a workspace-relative CSV path, the tool runs a battery of decision
oriented analyses and returns rich JSON plus the 3-6 most decision-relevant
charts as pinned ``ChartSpec`` dicts (on ``ToolResult.artifacts`` and mirrored
under ``data["charts"]``):

* ``describe``      -- shape, dtypes, missingness, numeric summaries.
* ``correlations``  -- Pearson correlation matrix, strongest pairs.
* ``groupbys``      -- auto-detected low-cardinality categoricals x numeric means.
* ``trends``        -- per-column linear slope, rolling mean, top movers.
* ``segmentation``  -- flag-like column (e.g. churn) rate by category.

Robustness: non-numeric columns and missing values are handled per operation;
empty files fail honestly; oversized files (> ``CSV_MAX_FILE_MB``, default
50 MB) are capped to the first ``CSV_ROW_CAP`` (default 100k) rows with an
explicit note; object/string columns that look like dates are coerced.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from agentforge_tools.base import Tool, ToolResult
from agentforge_tools.files import PathPolicyError, resolve_in_workspace

__all__ = ["CSVAnalyzerTool"]

KNOWN_OPERATIONS = ("describe", "correlations", "groupbys", "trends", "segmentation")

DEFAULT_MAX_FILE_MB = 50
DEFAULT_ROW_CAP = 100_000
_MAX_CHART_POINTS = 300
_MAX_SCATTER_POINTS = 500
_MAX_TOP_PAIRS = 10
_MAX_GROUPBY_COLS = 4
_MAX_SEGMENT_COLS = 4
_MAX_TREND_COLS = 12
_EPS = 1e-9

# Values treated as the "positive" (event-happened) side of a flag column.
_POSITIVE_LEXICON = {
    "yes", "y", "true", "t", "1", "churned", "churn", "cancelled", "canceled",
    "refunded", "returned", "failed", "defaulted",
}


# ---------------------------------------------------------------------------
# JSON-safety helpers
# ---------------------------------------------------------------------------

def _round(value: float, digits: int = 4) -> float:
    """Round a float for readable JSON output."""
    return float(round(float(value), digits))


def _json_safe(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars and containers to JSON types."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (pd.Series, np.ndarray)):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _label(value: Any) -> str:
    """Human label for a group key, mapping missing values to '(missing)'."""
    try:
        if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)):
            return "(missing)"
    except (TypeError, ValueError):
        pass
    return str(value)


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

class _Columns:
    """Classified columns of a dataframe."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.numeric: list[str] = [
            c for c in df.select_dtypes(include="number").columns
            if not pd.api.types.is_bool_dtype(df[c])
        ]
        self.boolean: list[str] = [
            c for c in df.columns if pd.api.types.is_bool_dtype(df[c])
        ]
        self.datetime: list[str] = [
            c for c in df.select_dtypes(include="datetime").columns
        ]
        skip = set(self.numeric) | set(self.boolean) | set(self.datetime)
        self.categorical: list[str] = [c for c in df.columns if c not in skip]

    def low_cardinality(self, df: pd.DataFrame, max_unique: int = 12) -> list[str]:
        """Categorical columns with a groupable number of distinct values."""
        if len(df) == 0:
            return []
        cap = min(max_unique, max(2, len(df) // 2))
        out: list[str] = []
        for col in self.categorical + self.boolean:
            try:
                nunique = int(df[col].nunique(dropna=True))
            except (TypeError, ValueError):
                continue
            if 2 <= nunique <= cap:
                out.append(col)
        return out


def _coerce_datetimes(df: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """Convert object/string columns that look like dates (>=80% parseable).

    Uses a sample to decide, then coerces the full column with
    ``errors="coerce"`` (unparseable entries become NaT and are treated as
    missing). Returns a new dataframe; never mutates the input.
    """
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]) or pd.api.types.is_bool_dtype(out[col]) \
                or pd.api.types.is_datetime64_any_dtype(out[col]):
            continue
        sample = out[col].dropna().astype(str).head(50)
        if sample.empty:
            continue
        try:
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
        except (TypeError, ValueError):
            try:
                parsed = pd.to_datetime(sample, errors="coerce")
            except (TypeError, ValueError):
                continue
        ratio = float(parsed.notna().mean()) if len(sample) else 0.0
        if ratio >= 0.8:
            try:
                full = pd.to_datetime(out[col], errors="coerce", format="mixed")
            except (TypeError, ValueError):
                full = pd.to_datetime(out[col], errors="coerce")
            out[col] = full
            notes.append(f"column {col!r} detected as datetime and parsed")
    return out


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _op_describe(df: pd.DataFrame, cols: _Columns) -> dict:
    """Describe: shape, per-column profile and numeric summary."""
    rows = int(len(df))
    column_profiles: list[dict] = []
    for col in df.columns:
        series = df[col]
        missing = int(series.isna().sum())
        profile: dict[str, Any] = {
            "name": str(col),
            "dtype": str(series.dtype),
            "non_null": rows - missing,
            "missing": missing,
            "missing_pct": _round(missing / rows * 100) if rows else 0.0,
        }
        if col in cols.numeric:
            profile["unique"] = int(series.nunique())
        else:
            profile["unique"] = int(series.nunique(dropna=True))
        examples = series.dropna().unique()[:5]
        profile["examples"] = [_json_safe(v) for v in examples]
        column_profiles.append(profile)

    numeric_summary: dict[str, dict] = {}
    if cols.numeric and rows:
        described = df[cols.numeric].describe().T
        for col, row in described.iterrows():
            numeric_summary[str(col)] = {
                "count": int(row.get("count", 0)),
                "mean": _round(row.get("mean", float("nan"))) if pd.notna(row.get("mean")) else None,
                "std": _round(row.get("std", float("nan"))) if pd.notna(row.get("std")) else None,
                "min": _round(row.get("min", float("nan"))) if pd.notna(row.get("min")) else None,
                "p25": _round(row.get("25%", float("nan"))) if pd.notna(row.get("25%")) else None,
                "median": _round(row.get("50%", float("nan"))) if pd.notna(row.get("50%")) else None,
                "p75": _round(row.get("75%", float("nan"))) if pd.notna(row.get("75%")) else None,
                "max": _round(row.get("max", float("nan"))) if pd.notna(row.get("max")) else None,
            }
    return {"rows": rows, "columns": int(df.shape[1]),
            "column_profiles": column_profiles, "numeric_summary": numeric_summary}


def _op_correlations(df: pd.DataFrame, cols: _Columns) -> dict:
    """Pearson correlations over numeric columns; strongest pairs first."""
    if len(cols.numeric) < 2:
        return {"note": "fewer than 2 numeric columns; correlations skipped", "top_pairs": []}
    corr = df[cols.numeric].corr(numeric_only=True)
    names = list(corr.columns)
    pairs: list[dict] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            value = corr.iloc[i, j]
            if pd.isna(value):
                continue
            pairs.append({"a": names[i], "b": names[j], "correlation": _round(float(value))})
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
    strong = [p for p in pairs if abs(p["correlation"]) >= 0.5]
    return {"top_pairs": pairs[:_MAX_TOP_PAIRS], "strong_pairs_count": len(strong)}


def _op_groupbys(df: pd.DataFrame, cols: _Columns) -> dict:
    """Aggregate numeric columns by auto-detected low-cardinality categoricals."""
    result: list[dict] = []
    if not cols.numeric:
        return {"groups": [], "note": "no numeric columns to aggregate"}
    numeric_subset = cols.numeric[:6]
    cat_cols = cols.low_cardinality(df)[:_MAX_GROUPBY_COLS]
    for cat in cat_cols:
        grouped = df.groupby(cat, dropna=False)[numeric_subset]
        means = grouped.mean()
        counts = grouped.size()
        groups: list[dict] = []
        for key in means.index:
            entry = {
                "value": _label(key),
                "count": int(counts.loc[key]),
                "means": {
                    str(num): _round(float(means.loc[key, num]))
                    for num in numeric_subset
                    if pd.notna(means.loc[key, num])
                },
            }
            groups.append(entry)
        groups.sort(key=lambda g: g["count"], reverse=True)
        result.append({"column": str(cat), "n_groups": len(groups), "groups": groups[:12]})
    if not result:
        return {"groups": [], "note": "no low-cardinality categorical columns detected"}
    return {"groups": result}


def _sorted_frame(df: pd.DataFrame, cols: _Columns, notes: list[str]) -> pd.DataFrame:
    """Sort by the first datetime column if present (for trend order)."""
    if cols.datetime:
        sort_col = cols.datetime[0]
        ordered = df.sort_values(sort_col, kind="stable").reset_index(drop=True)
        notes.append(f"trends computed after sorting rows by datetime column {sort_col!r}")
        return ordered
    notes.append("no datetime column detected; trends use file row order")
    return df.reset_index(drop=True)


def _op_trends(df: pd.DataFrame, cols: _Columns, notes: list[str]) -> dict:
    """Per-numeric-column slope, rolling mean, and top movers."""
    if len(df) < 3:
        return {"note": "fewer than 3 rows; trend detection skipped", "trends": [],
                "top_movers": []}
    ordered = _sorted_frame(df, cols, notes)
    trends: list[dict] = []
    window = max(3, min(10, len(ordered) // 5))
    for col in cols.numeric[:_MAX_TREND_COLS]:
        series = ordered[col].dropna().astype(float)
        if len(series) < 3:
            continue
        x = np.arange(len(series), dtype=float)
        try:
            slope = float(np.polyfit(x, series.to_numpy(dtype=float), 1)[0])
        except (np.linalg.LinAlgError, ValueError):
            continue
        scale = float(np.mean(np.abs(series.to_numpy()))) or 1.0
        normalized = slope / scale
        direction = "up" if normalized > 0.001 else ("down" if normalized < -0.001 else "flat")
        first = float(series.iloc[0])
        last = float(series.iloc[-1])
        rolling_last = _round(float(series.rolling(window, min_periods=1).mean().iloc[-1]))
        trends.append({
            "column": str(col),
            "slope_per_row": _round(slope),
            "normalized_slope": _round(normalized),
            "direction": direction,
            "first": _round(first),
            "last": _round(last),
            "change_pct": _round((last - first) / (abs(first) + _EPS) * 100),
            "rolling_window": int(window),
            "rolling_mean_last": rolling_last,
        })
    trends.sort(key=lambda t: abs(t["normalized_slope"]), reverse=True)
    return {
        "sort_basis": cols.datetime[0] if cols.datetime else "row_order",
        "trends": trends,
        "top_movers": trends[:3],
    }


def _detect_flag_column(df: pd.DataFrame, cols: _Columns) -> tuple[str, Any, pd.Series] | None:
    """Find a binary flag-like column; return (name, positive_value, mask)."""
    for col in cols.boolean:
        positive = True
        return col, positive, df[col].astype(bool)
    for col in cols.numeric:
        uniques = set(pd.unique(df[col].dropna()))
        if len(uniques) == 2:
            ordered_vals = sorted(uniques)
            positive = ordered_vals[-1]  # for 0/1 flags this is 1
            return col, positive, df[col] == positive
    for col in cols.categorical:
        values = [v for v in pd.unique(df[col].dropna())]
        lowered = {str(v).strip().lower(): v for v in values}
        if len(values) == 2:
            positive = None
            for low, original in lowered.items():
                if low in _POSITIVE_LEXICON:
                    positive = original
                    break
            if positive is None:
                positive = max(values, key=lambda v: str(v))
            return col, positive, df[col].astype(str).str.strip().str.lower() == str(positive).strip().lower()
    return None


def _op_segmentation(df: pd.DataFrame, cols: _Columns) -> dict:
    """Rate of the positive flag value overall and by categorical column."""
    if len(df) == 0:
        return {"note": "no rows to segment"}
    detected = _detect_flag_column(df, cols)
    if detected is None:
        return {"note": "no binary flag-like column detected; segmentation skipped"}
    flag_col, positive, mask = detected
    overall_rate = float(mask.mean())
    breakdowns: list[dict] = []
    candidates = [c for c in cols.low_cardinality(df, max_unique=8) if c != flag_col]
    for cat in candidates[:_MAX_SEGMENT_COLS]:
        rates: list[dict] = []
        grouped_rate = df.assign(_flag=mask).groupby(cat, dropna=False)["_flag"].mean()
        grouped_count = df.groupby(cat, dropna=False).size()
        for key in grouped_rate.index:
            rate = grouped_rate.loc[key]
            if pd.isna(rate):
                continue
            rates.append({
                "value": _label(key),
                "count": int(grouped_count.loc[key]),
                "rate": _round(float(rate) * 100, 2),
            })
        rates.sort(key=lambda r: r["rate"], reverse=True)
        breakdowns.append({"column": str(cat), "rates": rates})
    return {
        "flag_column": str(flag_col),
        "positive_value": _json_safe(positive),
        "overall_rate_pct": _round(overall_rate * 100, 2),
        "by_category": breakdowns,
        "note": "rates are the share of rows where the flag is the positive value",
    }


# ---------------------------------------------------------------------------
# ChartSpec builders (each returns a ChartSpec dict or None)
# ---------------------------------------------------------------------------

def _chart_missing(profile: dict) -> dict | None:
    """Bar chart of missing values per column."""
    missing = [
        {"label": c["name"], "y": c["missing"]}
        for c in profile.get("column_profiles", [])
        if c.get("missing", 0) > 0
    ]
    if not missing:
        return None
    return {
        "id": "chart_missing", "kind": "bar",
        "title": "Missing values by column",
        "x_label": "Column", "y_label": "Missing cells",
        "data": missing,
        "notes": "Columns with the most missing values may bias downstream analysis.",
    }


def _chart_trend(ordered_df: pd.DataFrame, cols: _Columns, trends: dict) -> dict | None:
    """Line chart of the top-mover numeric column over time or row index."""
    movers = trends.get("top_movers") or []
    if not movers or ordered_df is None or len(ordered_df) < 3:
        return None
    target = movers[0]["column"]
    series = ordered_df[target].dropna()
    if len(series) < 3:
        return None
    if cols.datetime:
        xcol = cols.datetime[0]
        x_vals = ordered_df.loc[series.index, xcol]
        keep = x_vals.notna()
        if not bool(keep.all()):
            series = series[keep]
            x_vals = x_vals[keep]
            if len(series) < 3:
                return None
        xs = [str(v.date()) for v in x_vals]
        x_label = str(xcol)
    else:
        xs = [int(i) for i in series.index]
        x_label = "Row index"
    step = max(1, math.ceil(len(series) / _MAX_CHART_POINTS))
    xs, ys = xs[::step], [float(v) for v in series.iloc[::step]]
    return {
        "id": "chart_trend", "kind": "line",
        "title": f"{target} over {x_label}",
        "x_label": x_label, "y_label": str(target),
        "data": [
            {"label": str(x), "x": x, "y": _round(y)}
            for x, y in zip(xs, ys)
        ],
        "notes": (
            f"{target} is the strongest mover "
            f"(normalized slope {movers[0].get('normalized_slope')})."
        ),
    }


def _chart_flag_pie(segmentation: dict, df: pd.DataFrame, cols: _Columns) -> dict | None:
    """Pie chart of the flag column distribution."""
    flag_col = segmentation.get("flag_column")
    if not flag_col:
        return None
    counts = df[flag_col].value_counts(dropna=False)
    if counts.empty:
        return None
    data = [
        {"label": _label(key), "x": float(i), "y": float(counts.loc[key])}
        for i, key in enumerate(counts.index)
    ]
    return {
        "id": "chart_flag_split", "kind": "pie",
        "title": f"Split of {flag_col}",
        "x_label": "", "y_label": "Rows",
        "data": data,
        "notes": f"Positive value: {segmentation.get('positive_value')!r}; "
                 f"overall rate {segmentation.get('overall_rate_pct')}%.",
    }


def _chart_flag_by_cat(segmentation: dict) -> dict | None:
    """Bar chart of positive flag rate by the first breakdown category."""
    breakdowns = segmentation.get("by_category") or []
    if not breakdowns:
        return None
    cat, rates = breakdowns[0]["column"], breakdowns[0]["rates"]
    if not rates:
        return None
    return {
        "id": "chart_flag_by_cat", "kind": "bar",
        "title": f"{segmentation.get('flag_column')} rate by {cat}",
        "x_label": str(cat), "y_label": "Positive rate (%)",
        "data": [{"label": r["value"], "x": r["value"], "y": r["rate"]} for r in rates[:8]],
        "notes": "Segments above the overall rate are the natural first targets.",
    }


def _chart_group_means(groupbys: dict, trends: dict, cols: _Columns) -> dict | None:
    """Bar chart of one numeric metric's mean across a categorical group."""
    groups = groupbys.get("groups") or []
    movers = trends.get("top_movers") or []
    metric = movers[0]["column"] if movers else (cols.numeric[0] if cols.numeric else None)
    if not metric:
        return None
    # Prefer a categorical with 3-8 groups for readability, else 2.
    chosen = None
    for entry in groups:
        if 3 <= entry["n_groups"] <= 8:
            chosen = entry
            break
    if chosen is None:
        for entry in groups:
            if entry["n_groups"] == 2:
                chosen = entry
                break
    if chosen is None:
        return None
    rows = [
        {"label": g["value"], "x": g["value"], "y": g["means"][metric]}
        for g in chosen["groups"][:8] if metric in g["means"]
    ]
    if len(rows) < 2:
        return None
    return {
        "id": "chart_group_means", "kind": "bar",
        "title": f"Mean {metric} by {chosen['column']}",
        "x_label": str(chosen["column"]), "y_label": f"Mean {metric}",
        "data": rows,
        "notes": "Which segments over- or under-index on the key metric.",
    }


def _chart_scatter(correlations: dict, df: pd.DataFrame) -> dict | None:
    """Scatter chart of the strongest (|r| >= 0.25) numeric pair."""
    pairs = correlations.get("top_pairs") or []
    if not pairs or abs(pairs[0]["correlation"]) < 0.25:
        return None
    a, b, r = pairs[0]["a"], pairs[0]["b"], pairs[0]["correlation"]
    sub = df[[a, b]].dropna()
    if len(sub) < 5:
        return None
    step = max(1, math.ceil(len(sub) / _MAX_SCATTER_POINTS))
    sub = sub.iloc[::step]
    return {
        "id": "chart_scatter", "kind": "scatter",
        "title": f"{a} vs {b} (r={r})",
        "x_label": str(a), "y_label": str(b),
        "data": [
            {"label": "", "x": float(row[a]), "y": float(row[b])}
            for _, row in sub.iterrows()
        ],
        "notes": f"Pearson correlation {r}; strongest numeric relationship in the file.",
    }


_CHART_ORDER_DEFAULT = ["trend", "group_means", "flag_by_cat", "flag_pie", "scatter", "missing"]


def _chart_priority(question: str | None) -> list[str]:
    """Order chart candidates by the mission question's keywords."""
    q = (question or "").lower()
    if any(k in q for k in ("churn", "segment", "retention", "conversion", "attrition")):
        return ["flag_pie", "flag_by_cat", "group_means", "trend", "scatter", "missing"]
    if any(k in q for k in ("trend", "over time", "growth", "forecast", "predict", "season")):
        return ["trend", "group_means", "flag_by_cat", "flag_pie", "scatter", "missing"]
    if any(k in q for k in ("correlat", "relationship", "driver", "associated", "impact")):
        return ["scatter", "trend", "group_means", "flag_by_cat", "flag_pie", "missing"]
    if any(k in q for k in ("missing", "quality", "clean", "completeness")):
        return ["missing", "trend", "group_means", "flag_by_cat", "flag_pie", "scatter"]
    return list(_CHART_ORDER_DEFAULT)


def _build_charts(
    df: pd.DataFrame,
    ordered_df: pd.DataFrame | None,
    cols: _Columns,
    ops: dict[str, dict],
    question: str | None,
) -> list[dict]:
    """Assemble the 3-6 most decision-relevant ChartSpec dicts."""
    profile = ops.get("describe", {})
    correlations = ops.get("correlations", {})
    groupbys = ops.get("groupbys", {})
    trends = ops.get("trends", {})
    segmentation = ops.get("segmentation", {})

    candidates: dict[str, dict | None] = {
        "missing": _chart_missing(profile),
        "trend": _chart_trend(ordered_df, cols, trends) if ordered_df is not None else None,
        "flag_pie": _chart_flag_pie(segmentation, df, cols),
        "flag_by_cat": _chart_flag_by_cat(segmentation),
        "group_means": _chart_group_means(groupbys, trends, cols),
        "scatter": _chart_scatter(correlations, df),
    }
    ordered: list[dict] = []
    for key in _chart_priority(question):
        spec = candidates.get(key)
        if spec is not None:
            ordered.append(spec)

    charts = ordered[:6]
    for i, spec in enumerate(charts, start=1):
        spec["id"] = f"chart_{i}"
    return charts


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------

class CSVAnalyzerTool(Tool):
    """Tool: analyze a workspace CSV and return JSON insights + ChartSpecs."""

    name = "csv_analyzer"
    description = (
        "Analyze the uploaded CSV dataset in the workspace: column profiles "
        "and missing values, correlations, group-by breakdowns, trends with "
        "top movers, and segmentation by any flag-like column (e.g. churn). "
        "Returns a JSON summary plus 3-6 decision-relevant charts. Pass a "
        "question to focus the charts on what matters to the mission."
    )
    parameters_json_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to the .csv file.",
            },
            "question": {
                "type": "string",
                "description": (
                    "Optional business question; steers which charts are "
                    "considered most relevant."
                ),
            },
            "operations": {
                "type": "array",
                "description": (
                    "Optional subset of operations to run: describe, "
                    "correlations, groupbys, trends, segmentation. "
                    "Defaults to all."
                ),
                "items": {
                    "type": "string",
                    "enum": ["describe", "correlations", "groupbys", "trends", "segmentation"],
                },
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        workspace_dir: str | Path,
        max_file_mb: int | None = None,
        row_cap: int | None = None,
    ) -> None:
        """Create the analyzer rooted at ``workspace_dir``.

        Caps default from env ``CSV_MAX_FILE_MB`` (50) and ``CSV_ROW_CAP``
        (100000) and can be overridden per-instance (used by tests).
        """
        self._workspace = Path(workspace_dir).resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)

        def _env_int(env_name: str, default: int) -> int:
            raw = os.environ.get(env_name, "")
            try:
                return max(1, int(float(raw)))
            except (TypeError, ValueError):
                return default

        self._max_file_mb = max_file_mb or _env_int("CSV_MAX_FILE_MB", DEFAULT_MAX_FILE_MB)
        self._row_cap = row_cap or _env_int("CSV_ROW_CAP", DEFAULT_ROW_CAP)

    @property
    def workspace(self) -> Path:
        """The resolved workspace root."""
        return self._workspace

    # -- loading --------------------------------------------------------------

    def _load(self, resolved: Path, notes: list[str]) -> pd.DataFrame | None:
        """Read the CSV, honoring the size cap. Returns None on failure."""
        size = resolved.stat().st_size
        nrows: int | None = None
        if size > self._max_file_mb * 1024 * 1024:
            nrows = self._row_cap
            notes.append(
                f"file is larger than CSV_MAX_FILE_MB ({self._max_file_mb} MB); "
                f"analyzed only the first {self._row_cap} rows"
            )
        try:
            return pd.read_csv(resolved, nrows=nrows, encoding_errors="replace")
        except pd.errors.EmptyDataError:
            return None
        except Exception as exc:  # noqa: BLE001 - surface parse failures honestly
            raise ValueError(f"failed to parse CSV: {type(exc).__name__}: {exc}") from exc

    # -- tool entrypoint --------------------------------------------------------

    def run(self, inputs: dict) -> ToolResult:
        """Analyze ``inputs['path']``. Never raises."""
        raw_path = inputs.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return ToolResult(ok=False, error="csv_analyzer requires a non-empty 'path' string")

        try:
            resolved = resolve_in_workspace(self._workspace, raw_path)
        except PathPolicyError as exc:
            return ToolResult(ok=False, error=f"path rejected: {exc}")
        if not resolved.exists():
            return ToolResult(ok=False, error=f"file not found: {raw_path}")
        if resolved.is_dir():
            return ToolResult(ok=False, error=f"path is a directory: {raw_path}")

        question = inputs.get("question")
        if question is not None and not isinstance(question, str):
            return ToolResult(ok=False, error="'question' must be a string")

        raw_ops = inputs.get("operations")
        if raw_ops is None:
            ops_to_run = set(KNOWN_OPERATIONS)
        else:
            if not isinstance(raw_ops, list) or not all(isinstance(o, str) for o in raw_ops):
                return ToolResult(
                    ok=False, error="'operations' must be a list of operation names"
                )
            ops_to_run = set(raw_ops)
            unknown = ops_to_run - set(KNOWN_OPERATIONS)
            if unknown:
                return ToolResult(
                    ok=False,
                    error=f"unknown operations: {sorted(unknown)}; "
                          f"valid: {list(KNOWN_OPERATIONS)}",
                )
            if not ops_to_run:
                return ToolResult(ok=False, error="'operations' must not be empty")

        notes: list[str] = []
        try:
            df = self._load(resolved, notes)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        if df is None:
            return ToolResult(
                ok=False,
                data={"file": raw_path, "size_bytes": resolved.stat().st_size},
                error="CSV is empty (no parsable data rows)",
            )

        # Normalize column names; coerce date-looking columns.
        df.columns = [str(c).strip() for c in df.columns]
        df = _coerce_datetimes(df, notes)
        cols = _Columns(df)

        ops: dict[str, dict] = {}
        if "describe" in ops_to_run:
            ops["describe"] = _json_safe(_op_describe(df, cols))
        if "correlations" in ops_to_run:
            ops["correlations"] = _json_safe(_op_correlations(df, cols))
        if "groupbys" in ops_to_run:
            ops["groupbys"] = _json_safe(_op_groupbys(df, cols))
        if "trends" in ops_to_run:
            ops["trends"] = _json_safe(_op_trends(df, cols, notes))
        if "segmentation" in ops_to_run:
            ops["segmentation"] = _json_safe(_op_segmentation(df, cols))

        ordered_df = (
            _sorted_frame(df, cols, notes)
            if "trends" in ops_to_run and len(df) >= 3
            else None
        )
        charts = _build_charts(df, ordered_df, cols, ops, question)
        if len(charts) < 3:
            notes.append(
                f"only {len(charts)} chart(s) could be derived from this data"
            )
        if df.empty:
            notes.append("file contains headers but no data rows")

        summary = {
            "file": raw_path,
            "rows": int(len(df)),
            "columns": int(df.shape[1]),
            "column_names": [str(c) for c in df.columns],
            "question": question,
            "notes": notes,
        }
        data = {"summary": summary}
        data.update(ops)
        data["charts"] = charts
        return ToolResult(ok=True, data=data, artifacts=charts)
