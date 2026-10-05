"""Realistic fake RunResults for orchestrator.report tests (Agent 6).

Every fixture matches the ``RunResult.to_dict()`` shape pinned in
``docs/INTERFACES.md``:

    {run_id, mission, status, plan, steps, artifacts, token_usage, errors}

Four scenarios cover the demo surface:

* :func:`churn_run`        — succeeded churn-analysis run with text + chart +
  prediction + recommendation artifacts (the happy-path deliverable).
* :func:`empty_run`        — run that produced zero artifacts (honest empty
  report).
* :func:`partial_failed_run` — partial run with a failed step and errors.
* :func:`unsupported_claims_run` — run whose outputs contain absolute /
  vague claims the critic checklist must flag.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "churn_run",
    "empty_run",
    "partial_failed_run",
    "unsupported_claims_run",
    "make_prediction_artifact",
    "make_recommendation_artifact",
]


def churn_run() -> dict[str, Any]:
    """A realistic succeeded churn-analysis run (text/chart/pred/rec)."""
    return {
        "run_id": "run_churn_001",
        "mission": "Analyze why our churn spiked in Q3 and recommend 3 fixes",
        "status": "succeeded",
        "plan": [
            {
                "id": "st_1",
                "title": "Load and profile churn dataset",
                "agent": "analyst",
                "depends_on": [],
                "status": "completed",
            },
            {
                "id": "st_2",
                "title": "Cohort churn analysis",
                "agent": "analyst",
                "depends_on": ["st_1"],
                "status": "completed",
            },
            {
                "id": "st_3",
                "title": "Forecast Q4 churn",
                "agent": "forecaster",
                "depends_on": ["st_2"],
                "status": "completed",
            },
            {
                "id": "st_4",
                "title": "Recommend retention fixes",
                "agent": "critic",
                "depends_on": ["st_2"],
                "status": "completed",
            },
        ],
        "steps": [
            {
                "subtask_id": "st_1",
                "title": "Load and profile churn dataset",
                "agent": "analyst",
                "status": "completed",
                "summary": (
                    "The dataset has 4,120 rows and 11 columns. The churn rate "
                    "is 9.8% overall, up from 6.2% in Q2."
                ),
            },
            {
                "subtask_id": "st_2",
                "title": "Cohort churn analysis",
                "agent": "analyst",
                "status": "completed",
                "summary": (
                    "Churn among month-to-month contract customers reached "
                    "18.4% in Q3, versus 4.1% for annual contracts. Support "
                    "ticket volume correlates with churn (r=0.62)."
                ),
            },
            {
                "subtask_id": "st_3",
                "title": "Forecast Q4 churn",
                "agent": "forecaster",
                "status": "completed",
                "summary": (
                    "We predict Q4 churn of 11.2% if current trends continue, "
                    "based on the trailing 3-month trend and ticket volume."
                ),
            },
            {
                "subtask_id": "st_4",
                "title": "Recommend retention fixes",
                "agent": "critic",
                "status": "completed",
                "summary": "Recommendations were drafted from the cohort analysis.",
            },
        ],
        "artifacts": [
            {
                "artifact_id": "art_1",
                "kind": "text",
                "name": "Churn overview",
                "summary": (
                    "Overall churn rose from 6.2% in Q2 to 9.8% in Q3, a 58% "
                    "relative increase. The spike is concentrated in "
                    "month-to-month contracts."
                ),
                "subtask_id": "st_1",
            },
            {
                "artifact_id": "art_2",
                "kind": "chart",
                "name": "Churn by contract type",
                "summary": "Bar chart of churn rate by contract type",
                "subtask_id": "st_2",
                "data": {
                    "id": "chart_1",
                    "kind": "bar",
                    "title": "Churn rate by contract type",
                    "x_label": "Contract type",
                    "y_label": "Churn %",
                    "data": [
                        {"label": "Month-to-month", "x": 1, "y": 18.4},
                        {"label": "Annual", "x": 2, "y": 4.1},
                        {"label": "Two-year", "x": 3, "y": 2.7},
                    ],
                    "notes": "Churn is 4.5x higher for month-to-month customers.",
                },
            },
            make_prediction_artifact(
                artifact_id="art_3",
                name="Q4 churn forecast",
                claim="Q4 churn will reach 11.2% without intervention",
                confidence=0.78,
                basis="Trailing 3-month trend and rising support ticket volume",
                subtask_id="st_3",
            ),
            make_recommendation_artifact(
                artifact_id="art_4",
                name="Contract conversion offer",
                title="Convert month-to-month customers",
                action=(
                    "Launch a 15% discount campaign targeting month-to-month "
                    "customers with tenure over 6 months"
                ),
                expected_impact=(
                    "High: could reduce churn by 2-3 points, saving roughly "
                    "$420,000 annually"
                ),
                effort="M",
                subtask_id="st_2",
            ),
        ],
        "token_usage": {
            "per_agent": {
                "analyst": {
                    "input_tokens": 5200,
                    "output_tokens": 1800,
                    "cost_usd": 0.0140,
                },
                "forecaster": {
                    "input_tokens": 3100,
                    "output_tokens": 900,
                    "cost_usd": 0.0080,
                },
            },
            "totals": {
                "input_tokens": 12400,
                "output_tokens": 4100,
                "cost_usd": 0.0330,
            },
        },
        "errors": [],
    }


def empty_run() -> dict[str, Any]:
    """A run that finished without producing any artifacts."""
    return {
        "run_id": "run_empty_001",
        "mission": "Summarize our Q3 marketing performance",
        "status": "succeeded",
        "plan": [
            {
                "id": "st_1",
                "title": "Research market context",
                "agent": "researcher",
                "depends_on": [],
                "status": "completed",
            }
        ],
        "steps": [
            {
                "subtask_id": "st_1",
                "title": "Research market context",
                "agent": "researcher",
                "status": "completed",
                "summary": "No data sources were available for this mission.",
            }
        ],
        "artifacts": [],
        "token_usage": {
            "totals": {"input_tokens": 900, "output_tokens": 120, "cost_usd": 0.0021}
        },
        "errors": [],
    }


def partial_failed_run() -> dict[str, Any]:
    """A partial run: one worker failed, errors were recorded."""
    return {
        "run_id": "run_partial_001",
        "mission": "Assess pricing power for our core product line",
        "status": "partial",
        "plan": [
            {
                "id": "st_1",
                "title": "Profile pricing dataset",
                "agent": "analyst",
                "depends_on": [],
                "status": "completed",
            },
            {
                "id": "st_2",
                "title": "Forecast price elasticity",
                "agent": "forecaster",
                "depends_on": ["st_1"],
                "status": "failed",
            },
        ],
        "steps": [
            {
                "subtask_id": "st_1",
                "title": "Profile pricing dataset",
                "agent": "analyst",
                "status": "completed",
                "summary": (
                    "Average selling price rose 6.5% year over year while "
                    "unit volume fell 2.1%, suggesting mild elasticity."
                ),
            },
            {
                "subtask_id": "st_2",
                "title": "Forecast price elasticity",
                "agent": "forecaster",
                "status": "failed",
                "summary": "",
                "error": "SandboxTimeout: forecast job exceeded 30s",
            },
        ],
        "artifacts": [
            {
                "artifact_id": "art_p1",
                "kind": "text",
                "name": "Pricing profile",
                "summary": (
                    "Average selling price rose 6.5% year over year while unit "
                    "volume fell 2.1%, suggesting mild price elasticity."
                ),
                "subtask_id": "st_1",
            }
        ],
        "token_usage": {
            "totals": {"input_tokens": 2100, "output_tokens": 450, "cost_usd": 0.0051}
        },
        "errors": ["forecaster step failed: SandboxTimeout after 30s"],
    }


def unsupported_claims_run() -> dict[str, Any]:
    """A run whose outputs include absolute and vague, unsupported claims."""
    return {
        "run_id": "run_weak_001",
        "mission": "Tell me if our new onboarding will retain users",
        "status": "succeeded",
        "plan": [
            {
                "id": "st_1",
                "title": "Review onboarding copy",
                "agent": "researcher",
                "depends_on": [],
                "status": "completed",
            }
        ],
        "steps": [
            {
                "subtask_id": "st_1",
                "title": "Review onboarding copy",
                "agent": "researcher",
                "status": "completed",
                "summary": (
                    "The new onboarding is guaranteed to always retain users "
                    "and everyone will love it."
                ),
            }
        ],
        "artifacts": [
            {
                "artifact_id": "art_w1",
                "kind": "text",
                "name": "Onboarding verdict",
                "summary": (
                    "The new onboarding is guaranteed to always retain users "
                    "and everyone will love it. It simply works."
                ),
                "subtask_id": "st_1",
            },
            {
                "artifact_id": "art_w2",
                "kind": "prediction",
                "name": "Retention forecast",
                "summary": "Prediction artifact",
                "subtask_id": "st_1",
                "data": {"claim": "Retention will improve dramatically"},
            },
            {
                "artifact_id": "art_w3",
                "kind": "recommendation",
                "name": "Ship it",
                "summary": "Ship the new onboarding",
                "subtask_id": "st_1",
                "data": {"title": "Ship the new onboarding"},
            },
            {
                "artifact_id": "art_w4",
                "kind": "chart",
                "name": "Empty chart",
                "summary": "Chart with no data",
                "subtask_id": "st_1",
                "data": {
                    "id": "chart_empty",
                    "kind": "bar",
                    "title": "Empty chart",
                    "data": [],
                },
            },
        ],
        "token_usage": {},
        "errors": [],
    }


def make_prediction_artifact(
    artifact_id: str,
    name: str,
    claim: str,
    confidence: float,
    basis: str,
    subtask_id: str = "st_1",
) -> dict[str, Any]:
    """Build a pinned-shape prediction artifact dict."""
    return {
        "artifact_id": artifact_id,
        "kind": "prediction",
        "name": name,
        "summary": f"Prediction artifact: {name}",
        "subtask_id": subtask_id,
        "data": {"claim": claim, "confidence": confidence, "basis": basis},
    }


def make_recommendation_artifact(
    artifact_id: str,
    name: str,
    title: str,
    action: str,
    expected_impact: str,
    effort: str = "M",
    subtask_id: str = "st_1",
) -> dict[str, Any]:
    """Build a pinned-shape recommendation artifact dict."""
    return {
        "artifact_id": artifact_id,
        "kind": "recommendation",
        "name": name,
        "summary": f"Recommendation artifact: {title}",
        "subtask_id": subtask_id,
        "data": {
            "title": title,
            "action": action,
            "expected_impact": expected_impact,
            "effort": effort,
        },
    }
