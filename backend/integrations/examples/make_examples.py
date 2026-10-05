"""Generate the committed n8n export examples for Devpost screenshots.

Creates two realistic AgentForge run snapshots (a ``market_research_team``
run and a ``sales_insights_team`` run, matching the pinned template
``expected_dag`` shapes) and exports each one with
``integrations.n8n_export.export_n8n``.

Outputs (written next to this script):
- ``market_research_team_snapshot.json``  -> exported ``market_research_team_workflow.json``
- ``sales_insights_team_snapshot.json``   -> exported ``sales_insights_team_workflow.json``

Run from anywhere::

    python backend/integrations/examples/make_examples.py

Everything is deterministic (fixed run ids, fixed timestamps) so re-running
the script reproduces the committed JSONs byte-for-byte. The snapshots are
synthetic-but-honest demo data: no real API keys, no fabricated metrics about
real companies — the numbers are clearly illustrative sample values.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Make `integrations` importable regardless of the caller's cwd.
# (examples/ -> integrations/ -> backend/)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from integrations.n8n_export import export_n8n  # noqa: E402  (path set above)

EXAMPLES_DIR = Path(__file__).resolve().parent


def _event(run_id: str, event_type: str, seq: int, agent: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Build one pinned Event envelope."""
    return {
        "type": event_type,
        "run_id": run_id,
        "seq": seq,
        "ts": f"2026-10-05T14:{seq // 60:02d}:{seq % 60:02d}Z",
        "agent": agent,
        "payload": payload,
    }


def _build_snapshot(
    run_id: str,
    mission_id: str,
    template_id: str,
    goal: str,
    subtasks: list[dict[str, Any]],
    style: str,
    extra_artifacts: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a full GET /api/runs/{id}-shaped snapshot with realistic events."""
    events: list[dict[str, Any]] = []
    seq = 0

    def next_event(event_type: str, agent: str | None, payload: dict[str, Any]) -> None:
        nonlocal seq
        seq += 1
        events.append(_event(run_id, event_type, seq, agent, payload))

    next_event("run_started", None, {"mode": "demo", "template_id": template_id})
    next_event("plan_created", "planner", {"subtasks": subtasks})
    next_event("token_update", "planner", {
        "agent": "planner", "input_tokens": 910, "output_tokens": 240,
        "cost_usd": 0.0001265, "run_total_usd": 0.0001265,
    })

    artifact_events: list[dict[str, Any]] = []
    for subtask in subtasks:
        next_event("agent_started", subtask["agent"], {"subtask_id": subtask["id"], "title": subtask["title"]})
        next_event("thought_summary", subtask["agent"], {
            "subtask_id": subtask["id"],
            "summary": f"Working on: {subtask['title'].lower()} — staying within the dataset and verified sources.",
        })
        next_event("tool_call", subtask["agent"], {
            "subtask_id": subtask["id"], "tool": "csv_analyzer" if subtask["agent"] == "analyst" else "llm_complete",
            "args_summary": "profile columns, dtypes, trends" if subtask["agent"] == "analyst" else "summarize context",
            "ok": True,
        })
        next_event("tool_result", subtask["agent"], {
            "subtask_id": subtask["id"], "tool": "csv_analyzer" if subtask["agent"] == "analyst" else "llm_complete",
            "args_summary": "ok", "ok": True,
        })
        for artifact in extra_artifacts:
            if artifact.get("subtask_id") == subtask["id"]:
                artifact_events.append(artifact)
                next_event("artifact_created", subtask["agent"], {
                    "subtask_id": subtask["id"],
                    "artifact_id": artifact["id"],
                    "kind": artifact["kind"],
                    "name": artifact["name"],
                    "summary": artifact["summary"],
                })
        next_event("token_update", subtask["agent"], {
            "agent": subtask["agent"],
            "input_tokens": 1240, "output_tokens": 380,
            "cost_usd": 0.0001782,
            "run_total_usd": round(0.0001265 + 0.0001782 * (subtasks.index(subtask) + 1), 7),
        })
        next_event("step_completed", subtask["agent"], {"subtask_id": subtask["id"]})
        next_event("agent_finished", subtask["agent"], {"subtask_id": subtask["id"]})

    next_event("run_finished", None, {"report_ready": True})

    return {
        "run": {
            "id": run_id,
            "mission_id": mission_id,
            "status": "succeeded",
            "created_at": "2026-10-05T14:00:00Z",
            "finished_at": "2026-10-05T14:06:12Z",
            "mode": "demo",
            "template_id": template_id,
            "error": None,
            "error_stage": None,
        },
        "mission": {
            "id": mission_id,
            "goal": goal,
            "template_id": template_id,
            "dataset_id": "ds-sample-01",
            "created_at": "2026-10-05T13:58:41Z",
        },
        "events": events,
        "artifacts": extra_artifacts,
        "token_usage": {
            "per_agent": {
                "planner": {"input_tokens": 910, "output_tokens": 240, "cost_usd": 0.0001265},
                "researcher": {"input_tokens": 1240, "output_tokens": 380, "cost_usd": 0.0001782},
                "analyst": {"input_tokens": 1610, "output_tokens": 520, "cost_usd": 0.0002343},
                "forecaster": {"input_tokens": 1180, "output_tokens": 310, "cost_usd": 0.0001639},
                "critic": {"input_tokens": 1520, "output_tokens": 460, "cost_usd": 0.0002178},
            },
            "totals": {"input_tokens": 6460, "output_tokens": 1910, "cost_usd": 0.0009207},
        },
        "report": report,
    }


def _market_research_case() -> tuple[dict[str, Any], str]:
    """market_research_team run: demand assessment for a meal-planning app."""
    run_id = "5c1e8a2f-93b4-4d17-ae55-6f0c2b9d8e41"
    mission_id = "m-7d3f2a01-5c6b-4e29-9a18-0b7c4d5e6f70"
    subtasks = [
        {"id": "st1", "title": "Frame the research questions and plan", "agent": "planner", "depends_on": [], "status": "completed"},
        {"id": "st2", "title": "Gather market and competitor context", "agent": "researcher", "depends_on": ["st1"], "status": "completed"},
        {"id": "st3", "title": "Profile the dataset and extract trends", "agent": "analyst", "depends_on": ["st1"], "status": "completed"},
        {"id": "st4", "title": "Project demand trend for the next period", "agent": "forecaster", "depends_on": ["st3"], "status": "completed"},
        {"id": "st5", "title": "Stress-test claims and rank recommendations", "agent": "critic", "depends_on": ["st2", "st3", "st4"], "status": "completed"},
    ]
    artifacts = [
        {
            "id": "art-mkt-1", "run_id": run_id, "subtask_id": "st3", "kind": "table",
            "name": "monthly_signups_trend", "summary": "Monthly signups and MoM growth from the sample CSV",
            "path": None,
            "payload": {"columns": ["month", "signups", "mom_growth_pct"]},
            "created_at": "2026-10-05T14:02:10Z",
        },
        {
            "id": "art-mkt-2", "run_id": run_id, "subtask_id": "st3", "kind": "chart",
            "name": "signups_by_city_size", "summary": "Bar chart: signups by city size tier",
            "path": None,
            "payload": {"chart": {"id": "chart_1", "kind": "bar", "title": "Signups by city size"}},
            "created_at": "2026-10-05T14:02:48Z",
        },
        {
            "id": "art-mkt-3", "run_id": run_id, "subtask_id": "st4", "kind": "prediction",
            "name": "demand_forecast", "summary": "Linear-trend projection of signups for the next 2 periods (confidence 0.62)",
            "path": None,
            "payload": {"confidence": 0.62},
            "created_at": "2026-10-05T14:03:55Z",
        },
    ]
    report = {
        "title": "Demand Assessment — Subscription Meal-Planning App (Mid-Size US Cities)",
        "mission": "Assess whether there is demand for a subscription meal-planning app in mid-size US cities and recommend a launch position.",
        "style": "market_research",
        "executive_summary": (
            "Sample-data trends show steady signup growth concentrated in mid-size cities, with "
            "weeknight dinner planning as the dominant stated use case. Demand signals are "
            "moderate, not proven: the dataset is small and the forecast carries wide uncertainty."
        ),
        "insights": [
            {"title": "Mid-size cities drive the majority of sample signups", "detail": "City-size tier breakdown shows the mid-size tier leading.", "evidence": ["signups_by_city_size table", "sample CSV rows 1-240"], "strength": "medium"},
            {"title": "Signups grow month over month in the sample window", "detail": "MoM growth is positive across all six sample months.", "evidence": ["monthly_signups_trend table"], "strength": "medium"},
            {"title": "Competitor set is fragmented", "detail": "Researcher found no single dominant incumbent in the stated niche (web sources, unverified beyond top results).", "evidence": ["researcher summary"], "strength": "low"},
        ],
        "charts": [
            {"id": "chart_1", "kind": "bar", "title": "Signups by city size", "x_label": "City size tier", "y_label": "Signups", "data": [{"label": "small", "x": 1, "y": 410}, {"label": "mid", "x": 2, "y": 980}, {"label": "large", "x": 3, "y": 760}], "notes": "Sample data; illustrative."},
        ],
        "predictions": [
            {"claim": "Signups continue a modest upward trend next period", "confidence": 0.62, "basis": "Linear trend over six sample months"},
        ],
        "recommendations": [
            {"title": "Pilot in two mid-size metros", "action": "Run a 6-week paid pilot targeting the mid-size tier.", "expected_impact": "Validates demand signal before broader spend", "effort": "M", "priority": 1},
            {"title": "Sharpen weeknight-dinner positioning", "action": "Test messaging around weeknight dinner planning in landing copy.", "expected_impact": "Higher signup conversion from stated intent", "effort": "S", "priority": 2},
            {"title": "Grow the sample before scaling forecasts", "action": "Collect another 2-3 months of data to tighten the forecast interval.", "expected_impact": "Reduces forecast uncertainty for the launch decision", "effort": "S", "priority": 3},
        ],
        "appendix": "Generated in demo mode with deterministic sample data (LLM_MODE=mock).",
    }
    snapshot = _build_snapshot(
        run_id, mission_id, "market_research_team",
        "Assess whether there is demand for a subscription meal-planning app in mid-size US cities and recommend a launch position.",
        subtasks, "market_research", artifacts, report,
    )
    return snapshot, run_id


def _sales_insights_case() -> tuple[dict[str, Any], str]:
    """sales_insights_team run: quarterly sales miss diagnosis."""
    run_id = "b9a4f7d2-2c58-4e93-8f61-3a7d5c0e9b12"
    mission_id = "m-2e8b4c90-1d7a-4f35-b642-9c0e5a1d3f84"
    subtasks = [
        {"id": "st1", "title": "Frame the sales questions and plan", "agent": "planner", "depends_on": [], "status": "completed"},
        {"id": "st2", "title": "Collect KPI and seasonality context", "agent": "researcher", "depends_on": ["st1"], "status": "completed"},
        {"id": "st3", "title": "Profile sales data and find drivers", "agent": "analyst", "depends_on": ["st1"], "status": "completed"},
        {"id": "st4", "title": "Forecast next-period revenue", "agent": "forecaster", "depends_on": ["st3"], "status": "completed"},
        {"id": "st5", "title": "Validate findings and rank fixes", "agent": "critic", "depends_on": ["st2", "st3", "st4"], "status": "completed"},
    ]
    artifacts = [
        {
            "id": "art-sales-1", "run_id": run_id, "subtask_id": "st3", "kind": "table",
            "name": "revenue_by_region", "summary": "Revenue and variance vs target by region",
            "path": None,
            "payload": {"columns": ["region", "revenue", "vs_target_pct"]},
            "created_at": "2026-10-05T15:02:30Z",
        },
        {
            "id": "art-sales-2", "run_id": run_id, "subtask_id": "st3", "kind": "chart",
            "name": "revenue_trend_weekly", "summary": "Line chart: weekly revenue with 4-week moving average",
            "path": None,
            "payload": {"chart": {"id": "chart_1", "kind": "line", "title": "Weekly revenue trend"}},
            "created_at": "2026-10-05T15:03:02Z",
        },
        {
            "id": "art-sales-3", "run_id": run_id, "subtask_id": "st4", "kind": "prediction",
            "name": "next_period_revenue", "summary": "Next-period revenue projection from 12-week trend (confidence 0.58)",
            "path": None,
            "payload": {"confidence": 0.58},
            "created_at": "2026-10-05T15:04:19Z",
        },
    ]
    report = {
        "title": "Q3 Sales Miss — Drivers and Recommended Fixes",
        "mission": "Analyze last quarter's sales CSV to find which regions and products drove the miss, and recommend 3 fixes for next quarter.",
        "style": "sales_insights",
        "executive_summary": (
            "The sample-quarter miss concentrates in two regions and one product line, with the "
            "weekly trend flattening in the back half of the quarter. The projected next-period "
            "recovery is modest; the ranked fixes target pipeline coverage and the weakest product line."
        ),
        "insights": [
            {"title": "Two regions account for most of the miss", "detail": "Regional variance table shows those regions furthest below target.", "evidence": ["revenue_by_region table"], "strength": "high"},
            {"title": "One product line drags the average", "detail": "Product-level breakdown flags the lowest-margin line as the largest negative contributor.", "evidence": ["revenue_by_region table", "analyst summary"], "strength": "medium"},
            {"title": "Weekly trend flattened in the back half", "detail": "4-week moving average turns flat after week 8 of the sample.", "evidence": ["revenue_trend_weekly chart"], "strength": "medium"},
        ],
        "charts": [
            {"id": "chart_1", "kind": "line", "title": "Weekly revenue trend", "x_label": "Week", "y_label": "Revenue", "data": [{"label": "w1", "x": 1, "y": 118}, {"label": "w2", "x": 2, "y": 124}, {"label": "w3", "x": 3, "y": 109}, {"label": "w4", "x": 4, "y": 96}], "notes": "Sample data; illustrative."},
        ],
        "predictions": [
            {"claim": "Next-period revenue recovers only partially without intervention", "confidence": 0.58, "basis": "12-week linear trend on sample data"},
        ],
        "recommendations": [
            {"title": "Rebuild pipeline coverage in the two lagging regions", "action": "Add coverage and review deal-stage conversion weekly for those regions.", "expected_impact": "Closes the largest share of the gap", "effort": "M", "priority": 1},
            {"title": "Sunset or reprice the weakest product line", "action": "Evaluate repricing vs retirement for the flagged line.", "expected_impact": "Stops the largest negative contributor", "effort": "M", "priority": 2},
            {"title": "Instrument weekly trend alerts", "action": "Alert on flat 4-week moving average so the next miss is caught mid-quarter.", "expected_impact": "Earlier detection, smaller misses", "effort": "S", "priority": 3},
        ],
        "appendix": "Generated in demo mode with deterministic sample data (LLM_MODE=mock).",
    }
    snapshot = _build_snapshot(
        run_id, mission_id, "sales_insights_team",
        "Analyze last quarter's sales CSV to find which regions and products drove the miss, and recommend 3 fixes for next quarter.",
        subtasks, "sales_insights", artifacts, report,
    )
    return snapshot, run_id


def main() -> int:
    """Generate all example files and print a summary. Returns a process exit code."""
    cases = [
        ("market_research_team", _market_research_case()),
        ("sales_insights_team", _sales_insights_case()),
    ]
    for name, (snapshot, _run_id) in cases:
        workflow = export_n8n(snapshot)

        snapshot_path = EXAMPLES_DIR / f"{name}_snapshot.json"
        workflow_path = EXAMPLES_DIR / f"{name}_workflow.json"
        snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        workflow_path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        meta = workflow["meta"]
        print(f"{name}:")
        print(f"  snapshot  -> {snapshot_path.name} ({snapshot_path.stat().st_size} bytes)")
        print(f"  workflow  -> {workflow_path.name} ({workflow_path.stat().st_size} bytes)")
        print(f"  nodes={meta['node_count']} edges={meta['edge_count']} plan_source={meta['plan_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
