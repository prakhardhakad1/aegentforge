"""Internal demo run emitter (RUN_MODE=demo fallback).

Used only when ``realtime.simulate.SimulatedRunPlayer`` (Agent 7) is not
importable or not drivable. Deterministic, fully offline, no LLM calls. Every
payload is labeled as simulated so the UI and reports can disclose it honestly.

Emits the full pinned event sequence:
    run_started -> plan_created -> (agent_started -> thought_summary ->
    tool_call -> tool_result -> [artifact_created] -> step_completed ->
    agent_finished -> token_update) per subtask
The caller (app.services.runner) persists the report + token usage and emits
the final ``run_finished`` after finalizing the run row.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from app.services.events import EventEmitter

logger = logging.getLogger("agentforge.demo_runner")

EVENT_DELAY_SECONDS = 0.02  # pacing so the UI can watch events stream

DEFAULT_PLAN: list[dict[str, Any]] = [
    {
        "id": "st1",
        "title": "Frame the mission and work plan",
        "agent": "planner",
        "depends_on": [],
        "status": "pending",
    },
    {
        "id": "st2",
        "title": "Gather external context and references",
        "agent": "researcher",
        "depends_on": ["st1"],
        "status": "pending",
    },
    {
        "id": "st3",
        "title": "Analyze the business data",
        "agent": "analyst",
        "depends_on": ["st1"],
        "status": "pending",
    },
    {
        "id": "st4",
        "title": "Project near-term trends",
        "agent": "forecaster",
        "depends_on": ["st3"],
        "status": "pending",
    },
    {
        "id": "st5",
        "title": "Stress-test findings and rank recommendations",
        "agent": "critic",
        "depends_on": ["st2", "st3", "st4"],
        "status": "pending",
    },
]

_TOOL_BY_AGENT: dict[str, str] = {
    "planner": "plan_dag",
    "researcher": "web_search",
    "analyst": "csv_profile",
    "forecaster": "linear_forecast",
    "critic": "claim_check",
}

_ARTIFACT_BY_AGENT: dict[str, dict[str, str]] = {
    "researcher": {
        "kind": "text",
        "name": "context_notes",
        "summary": "Simulated context notes gathered for the mission (demo).",
    },
    "analyst": {
        "kind": "table",
        "name": "dataset_summary",
        "summary": "Simulated table summarizing the dataset profile (demo).",
    },
    "forecaster": {
        "kind": "prediction",
        "name": "trend_prediction",
        "summary": "Simulated near-term trend prediction with stated confidence (demo).",
    },
    "critic": {
        "kind": "recommendation",
        "name": "ranked_recommendations",
        "summary": "Simulated ranked recommendations after claim review (demo).",
    },
}


async def run_demo_mission(
    *,
    run_id: str,
    mission: str,
    emitter: EventEmitter,
    template: Optional[dict[str, Any]] = None,
    dataset_info: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> dict[str, Any]:
    """Drive one simulated run and return ``{"report": {...}}``.

    The token/cost meter is accumulated automatically by the emitter from the
    ``token_update`` events emitted here.
    """
    del run_id  # emitter already carries it
    plan = _plan_from_template(template) or [dict(node) for node in DEFAULT_PLAN]
    columns = list((dataset_info or {}).get("columns") or [])
    row_count = int((dataset_info or {}).get("row_count") or 0)

    await emitter.emit(
        "run_started",
        agent=None,
        payload={"mission": mission, "mode": "demo", "simulated": True},
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    await emitter.emit("plan_created", agent="planner", payload={"subtasks": plan})
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    for index, subtask in enumerate(plan, start=1):
        agent = subtask.get("agent") or "planner"
        subtask_id = subtask.get("id") or f"st{index}"
        title = subtask.get("title") or f"Subtask {index}"
        await _emit_subtask(
            emitter,
            agent=agent,
            subtask_id=subtask_id,
            title=title,
            index=index,
            columns=columns,
            row_count=row_count,
            mission=mission,
        )

    report = build_demo_report(
        mission=mission, template=template, dataset_info=dataset_info, plan=plan
    )
    return {"report": report}


def _plan_from_template(template: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use the template's expected DAG (augmented with status) when present."""
    if not template:
        return []
    dag = template.get("expected_dag")
    if not isinstance(dag, list) or not dag:
        return []
    plan: list[dict[str, Any]] = []
    for node in dag:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        plan.append(
            {
                "id": str(node["id"]),
                "title": str(node.get("title") or node["id"]),
                "agent": str(node.get("agent") or "planner"),
                "depends_on": [str(d) for d in (node.get("depends_on") or [])],
                "status": "pending",
            }
        )
    return plan


async def _emit_subtask(
    emitter: EventEmitter,
    *,
    agent: str,
    subtask_id: str,
    title: str,
    index: int,
    columns: list[str],
    row_count: int,
    mission: str,
) -> None:
    """Emit the full per-subtask event block."""
    tool = _TOOL_BY_AGENT.get(agent, "think")
    dataset_note = (
        f"{row_count} data rows across columns: {', '.join(columns)}"
        if columns
        else "no dataset was provided, working from the mission text"
    )

    await emitter.emit(
        "agent_started", agent=agent, payload={"subtask_id": subtask_id, "title": title}
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    await emitter.emit(
        "thought_summary",
        agent=agent,
        payload={
            "subtask_id": subtask_id,
            "summary": (
                f"Simulated {agent} pass on '{title}'. Working with "
                f"{dataset_note} (demo mode, no LLM)."
            ),
        },
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    await emitter.emit(
        "tool_call",
        agent=agent,
        payload={
            "subtask_id": subtask_id,
            "tool": tool,
            "args_summary": f"demo args for '{title[:60]}'",
            "ok": True,
        },
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    await emitter.emit(
        "tool_result",
        agent=agent,
        payload={
            "subtask_id": subtask_id,
            "tool": tool,
            "args_summary": f"demo result for '{title[:60]}'",
            "ok": True,
        },
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    artifact_spec = _ARTIFACT_BY_AGENT.get(agent)
    if artifact_spec:
        if agent == "analyst" and not columns:
            pass  # nothing real to tabulate; skip the artifact rather than fake one
        else:
            await emitter.emit(
                "artifact_created",
                agent=agent,
                payload={
                    "subtask_id": subtask_id,
                    "artifact_id": f"art_{uuid.uuid4().hex[:12]}",
                    "kind": artifact_spec["kind"],
                    "name": artifact_spec["name"],
                    "summary": _artifact_summary(agent, columns, row_count, mission),
                    "simulated": True,
                },
            )
            await asyncio.sleep(EVENT_DELAY_SECONDS)

    await emitter.emit("step_completed", agent=agent, payload={"subtask_id": subtask_id})
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    await emitter.emit(
        "agent_finished", agent=agent, payload={"subtask_id": subtask_id}
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)

    await _emit_token_update(emitter, agent=agent, index=index)


def _artifact_summary(
    agent: str, columns: list[str], row_count: int, mission: str
) -> str:
    """Honest, demo-labeled artifact summaries (no invented metrics)."""
    del mission
    if agent == "researcher":
        return (
            "Simulated research notes: key questions and assumptions for the "
            "mission, clearly labeled as demo output (no live web search ran)."
        )
    if agent == "analyst":
        return (
            f"Simulated profile of the uploaded dataset: {row_count} rows, "
            f"columns [{', '.join(columns)}]. Values are structural, not "
            "computed metrics (demo)."
        )
    if agent == "forecaster":
        return (
            "Simulated trend prediction for the next period; confidence and "
            "basis would be computed from real data in live mode (demo)."
        )
    if agent == "critic":
        return (
            "Simulated review: flagged claims that would need stronger "
            "evidence in live mode, with ranked recommendations (demo)."
        )
    return "Simulated artifact (demo)."


async def _emit_token_update(
    emitter: EventEmitter, *, agent: str, index: int
) -> None:
    """Emit a token_update event using the configured per-1M-token rates.

    Token counts are deterministic demo numbers, clearly not real LLM usage.
    """
    input_tokens = 320 + 47 * index
    output_tokens = 180 + 31 * index
    in_rate = 0.11
    out_rate = 0.11
    if emitter is not None and getattr(emitter, "session_factory", None) is not None:
        try:
            from app.config import get_settings

            settings = get_settings()
            in_rate = settings.cost_per_1m_input_tokens
            out_rate = settings.cost_per_1m_output_tokens
        except Exception:  # pragma: no cover - fall back to defaults
            pass
    cost = round(
        input_tokens / 1_000_000 * in_rate + output_tokens / 1_000_000 * out_rate, 6
    )
    usage = emitter.accumulated_usage()
    run_total = round(float(usage["totals"]["cost_usd"]) + cost, 6)
    await emitter.emit(
        "token_update",
        agent=agent,
        payload={
            "agent": agent,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "run_total_usd": run_total,
            "simulated": True,
        },
    )
    await asyncio.sleep(EVENT_DELAY_SECONDS)


def build_demo_report(
    *,
    mission: str,
    template: Optional[dict[str, Any]],
    dataset_info: Optional[dict[str, Any]],
    plan: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a canonical Report dict for the demo run.

    Honest by construction: it describes the mission and the dataset's
    structure, and says plainly that outputs are simulated demo output.
    """
    from app.templates_data import STYLE_BY_TEMPLATE

    template_id = (template or {}).get("id")
    style = STYLE_BY_TEMPLATE.get(template_id or "", "default")
    columns = list((dataset_info or {}).get("columns") or [])
    row_count = int((dataset_info or {}).get("row_count") or 0)
    agent_list = ", ".join(
        sorted({str(node.get("agent") or "planner") for node in plan})
    )

    insights: list[dict[str, Any]] = []
    if columns:
        insights.append(
            {
                "title": "Dataset coverage",
                "detail": (
                    f"The uploaded dataset provides {row_count} rows across "
                    f"{len(columns)} columns ({', '.join(columns)}). In live "
                    "mode the analyst agent would compute concrete trends "
                    "over these columns."
                ),
                "evidence": ["dataset columns/rows counted at upload time"],
                "strength": "medium",
            }
        )
    else:
        insights.append(
            {
                "title": "No dataset attached",
                "detail": (
                    "This mission ran without an uploaded CSV, so analysis is "
                    "limited to the mission text and external context. Attach "
                    "a dataset for data-backed insights."
                ),
                "evidence": ["mission payload"],
                "strength": "low",
            }
        )
    insights.append(
        {
            "title": "Simulated agent pipeline",
            "detail": (
                f"Demo mode executed a {len(plan)}-step plan across the "
                f"{agent_list} roles. All summaries are simulated placeholders "
                "with no LLM calls; switch RUN_MODE=live for real analysis."
            ),
            "evidence": ["RUN_MODE=demo"],
            "strength": "low",
        }
    )

    return {
        "title": f"Demo report — {mission[:70]}",
        "mission": mission,
        "style": style,
        "executive_summary": (
            "Simulated demo output (RUN_MODE=demo, no LLM was used): the agent "
            "team completed the planned steps and this report shows the shape "
            "of the final deliverable."
        ),
        "insights": insights,
        "charts": [],
        "predictions": [
            {
                "claim": (
                    "Demo placeholder prediction — live mode would project a "
                    "trend from your dataset with a stated confidence."
                ),
                "confidence": 0.0,
                "basis": "simulated (no data-backed computation ran)",
            }
        ],
        "recommendations": [
            {
                "title": "Review this demo report shape",
                "action": (
                    "Re-run this mission in live mode with a dataset to get "
                    "data-backed recommendations ranked by impact and effort."
                ),
                "expected_impact": "Enables real, evidence-based decisions",
                "effort": "S",
                "priority": 1,
            }
        ],
        "appendix": (
            "Generated by AgentForge demo mode (internal demo emitter). No LLM "
            "calls were made; all content is labeled simulated."
        ),
    }
