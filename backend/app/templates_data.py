"""The 3 pinned agent-team templates (docs/INTERFACES.md — exact ids).

These are served by GET /api/templates and seeded into the ``templates`` table
at startup. Agent 8's richer versions land later and will be reconciled; the
prompts here are real, concise planner/system prompts (no placeholders).

Template dict shape (pinned ``Template``):
    {id, name, description, tags, team: [{role, title, system_prompt}],
     planner_prompt, sample_mission, expected_dag: [{id, title, agent,
     depends_on}], report_outline}
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Template as TemplateModel

TEMPLATE_IDS: tuple[str, ...] = (
    "market_research_team",
    "sales_insights_team",
    "support_triage_team",
)

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "market_research_team",
        "name": "Market Research Team",
        "description": (
            "Researches a market, product, or competitor question end to end: "
            "gathers external context, profiles any uploaded data, projects "
            "trends, and stress-tests every claim before recommending next steps."
        ),
        "tags": ["research", "competition", "positioning", "trends"],
        "team": [
            {
                "role": "planner",
                "title": "Research Planner",
                "system_prompt": (
                    "You are the research planner for a market-research team. "
                    "Break the user's mission into a small DAG of subtasks "
                    "(3-6) assigned to researcher, analyst, forecaster and "
                    "critic agents. Respect depends_on ordering, keep each "
                    "subtask title under 12 words, and never invent data "
                    "sources."
                ),
            },
            {
                "role": "researcher",
                "title": "Market Researcher",
                "system_prompt": (
                    "You are a market researcher. Collect concise, citable "
                    "facts about the market/competitors in the mission. "
                    "Summarize in 3-5 bullets; label anything unverified as "
                    "assumption. Never fabricate statistics."
                ),
            },
            {
                "role": "analyst",
                "title": "Data Analyst",
                "system_prompt": (
                    "You are a business data analyst. Profile the uploaded CSV "
                    "(columns, dtypes, data quality), compute descriptive "
                    "stats and trends, and produce one table artifact per "
                    "finding. If no dataset exists, say so explicitly instead "
                    "of inventing numbers."
                ),
            },
            {
                "role": "forecaster",
                "title": "Trend Forecaster",
                "system_prompt": (
                    "You are a forecaster. From the analyst's outputs, project "
                    "near-term trends with a simple, explainable method "
                    "(e.g. linear trend). Always state a confidence in [0,1] "
                    "and the basis of the prediction."
                ),
            },
            {
                "role": "critic",
                "title": "Research Critic",
                "system_prompt": (
                    "You are the critic. Review every insight and prediction "
                    "for unsupported claims, weak evidence, or sample-size "
                    "issues. Downgrade weak claims, then rank 3-5 "
                    "recommendations by expected impact vs effort."
                ),
            },
        ],
        "planner_prompt": (
            "Plan this market-research mission as a DAG of 3-6 subtasks for "
            "the roles researcher, analyst, forecaster, critic. The analyst "
            "must run before the forecaster; the critic must run last and "
            "depend on all other subtasks. Mission: {mission}. Dataset "
            "columns: {dataset_columns}."
        ),
        "sample_mission": (
            "Assess whether there is demand for a subscription meal-planning "
            "app in mid-size US cities and recommend a launch position."
        ),
        "expected_dag": [
            {
                "id": "st1",
                "title": "Frame the research questions and plan",
                "agent": "planner",
                "depends_on": [],
            },
            {
                "id": "st2",
                "title": "Gather market and competitor context",
                "agent": "researcher",
                "depends_on": ["st1"],
            },
            {
                "id": "st3",
                "title": "Profile the dataset and extract trends",
                "agent": "analyst",
                "depends_on": ["st1"],
            },
            {
                "id": "st4",
                "title": "Project demand trend for the next period",
                "agent": "forecaster",
                "depends_on": ["st3"],
            },
            {
                "id": "st5",
                "title": "Stress-test claims and rank recommendations",
                "agent": "critic",
                "depends_on": ["st2", "st3", "st4"],
            },
        ],
        "report_outline": [
            "Executive summary",
            "Market context (researcher)",
            "Data landscape and quality (analyst)",
            "Trend outlook (forecaster)",
            "Risk review (critic)",
            "Ranked recommendations",
        ],
    },
    {
        "id": "sales_insights_team",
        "name": "Sales Insights Team",
        "description": (
            "Turns a sales/revenue CSV into clear insights: profiles the "
            "pipeline data, finds trends and outliers, forecasts the next "
            "period, and ranks the actions most likely to lift revenue."
        ),
        "tags": ["sales", "revenue", "forecasting", "csv"],
        "team": [
            {
                "role": "planner",
                "title": "Sales Analysis Planner",
                "system_prompt": (
                    "You are the planner for a sales-insights team. Decompose "
                    "the mission into 3-6 subtasks across researcher, analyst, "
                    "forecaster, critic. Analyst work must precede "
                    "forecasting; the critic closes the loop. Prefer subtasks "
                    "that read from the uploaded dataset."
                ),
            },
            {
                "role": "researcher",
                "title": "Sales Context Researcher",
                "system_prompt": (
                    "You are a sales research assistant. Provide brief "
                    "external context for the mission (seasonality norms, "
                    "common KPI definitions). Keep it to 3-5 bullets and "
                    "mark unverified items as assumptions."
                ),
            },
            {
                "role": "analyst",
                "title": "Revenue Analyst",
                "system_prompt": (
                    "You are a revenue analyst. Profile the CSV (rows, "
                    "columns, dtypes, missing values), compute per-dimension "
                    "totals and trends, and emit a table artifact per finding. "
                    "Use only values present in the data."
                ),
            },
            {
                "role": "forecaster",
                "title": "Revenue Forecaster",
                "system_prompt": (
                    "You are a revenue forecaster. Fit a simple trend on the "
                    "analyst's series and predict the next period. Report "
                    "confidence in [0,1], the basis, and the main risk to the "
                    "projection."
                ),
            },
            {
                "role": "critic",
                "title": "Sales Insights Critic",
                "system_prompt": (
                    "You are the critic for sales insights. Challenge every "
                    "claimed driver of revenue: is the evidence in the data? "
                    "Downgrade weak claims and rank 3-5 recommendations with "
                    "expected impact and S/M/L effort."
                ),
            },
        ],
        "planner_prompt": (
            "Plan this sales-insights mission as a DAG of 3-6 subtasks. The "
            "analyst must profile the dataset before the forecaster projects "
            "trends; the critic must depend on all prior subtasks. Mission: "
            "{mission}. Dataset columns: {dataset_columns}."
        ),
        "sample_mission": (
            "Analyze last quarter's sales CSV to find which regions and "
            "products drove the miss, and recommend 3 fixes for next quarter."
        ),
        "expected_dag": [
            {
                "id": "st1",
                "title": "Frame the sales questions and plan",
                "agent": "planner",
                "depends_on": [],
            },
            {
                "id": "st2",
                "title": "Collect KPI and seasonality context",
                "agent": "researcher",
                "depends_on": ["st1"],
            },
            {
                "id": "st3",
                "title": "Profile sales data and find drivers",
                "agent": "analyst",
                "depends_on": ["st1"],
            },
            {
                "id": "st4",
                "title": "Forecast next-period revenue",
                "agent": "forecaster",
                "depends_on": ["st3"],
            },
            {
                "id": "st5",
                "title": "Validate findings and rank fixes",
                "agent": "critic",
                "depends_on": ["st2", "st3", "st4"],
            },
        ],
        "report_outline": [
            "Executive summary",
            "Pipeline context (researcher)",
            "Sales data findings (analyst)",
            "Next-period forecast (forecaster)",
            "Claim review (critic)",
            "Ranked recommendations",
        ],
    },
    {
        "id": "support_triage_team",
        "name": "Support Triage Team",
        "description": (
            "Mines a support-ticket export for volume spikes, top themes and "
            "SLA risk; forecasts ticket load for the coming period and "
            "recommends triage and staffing fixes."
        ),
        "tags": ["support", "cx", "triage", "tickets"],
        "team": [
            {
                "role": "planner",
                "title": "Support Triage Planner",
                "system_prompt": (
                    "You are the planner for a support-triage team. Split the "
                    "mission into 3-6 subtasks for researcher, analyst, "
                    "forecaster, critic. The analyst reads the ticket export "
                    "first; the forecaster projects load; the critic verifies "
                    "and ranks actions."
                ),
            },
            {
                "role": "researcher",
                "title": "CX Researcher",
                "system_prompt": (
                    "You are a customer-experience researcher. Summarize "
                    "common ticket-taxonomy and SLA conventions relevant to "
                    "the mission in 3-5 bullets. Flag anything unverifiable."
                ),
            },
            {
                "role": "analyst",
                "title": "Ticket Analyst",
                "system_prompt": (
                    "You are a support analyst. Profile the ticket CSV: "
                    "volume by category/priority over time, response-time "
                    "stats, and data-quality notes. Emit one table artifact "
                    "per finding using only real data values."
                ),
            },
            {
                "role": "forecaster",
                "title": "Load Forecaster",
                "system_prompt": (
                    "You are a support-load forecaster. Project ticket volume "
                    "for the next period from the analyst's series with a "
                    "simple explainable method; state confidence in [0,1] and "
                    "the basis."
                ),
            },
            {
                "role": "critic",
                "title": "Triage Critic",
                "system_prompt": (
                    "You are the critic for support triage. Check that each "
                    "claimed driver of ticket volume is actually supported by "
                    "the data, downgrade weak claims, and rank triage/staffing "
                    "recommendations by impact vs effort."
                ),
            },
        ],
        "planner_prompt": (
            "Plan this support-triage mission as a DAG of 3-6 subtasks. The "
            "analyst must profile the ticket export before forecasting; the "
            "critic must depend on every other subtask. Mission: {mission}. "
            "Dataset columns: {dataset_columns}."
        ),
        "sample_mission": (
            "Our support tickets spiked in September — find the top themes "
            "and SLA risks from the ticket CSV and recommend 3 triage fixes."
        ),
        "expected_dag": [
            {
                "id": "st1",
                "title": "Frame the triage questions and plan",
                "agent": "planner",
                "depends_on": [],
            },
            {
                "id": "st2",
                "title": "Review ticket taxonomy and SLA norms",
                "agent": "researcher",
                "depends_on": ["st1"],
            },
            {
                "id": "st3",
                "title": "Profile ticket volume and themes",
                "agent": "analyst",
                "depends_on": ["st1"],
            },
            {
                "id": "st4",
                "title": "Forecast ticket load next period",
                "agent": "forecaster",
                "depends_on": ["st3"],
            },
            {
                "id": "st5",
                "title": "Check claims and rank triage fixes",
                "agent": "critic",
                "depends_on": ["st2", "st3", "st4"],
            },
        ],
        "report_outline": [
            "Executive summary",
            "Support context (researcher)",
            "Ticket data findings (analyst)",
            "Load forecast (forecaster)",
            "Claim review (critic)",
            "Ranked recommendations",
        ],
    },
]

# Template id -> report style string used by the canonical Report model.
STYLE_BY_TEMPLATE: dict[str, str] = {
    "market_research_team": "market_research",
    "sales_insights_team": "sales_insights",
    "support_triage_team": "support_triage",
}


def get_template_spec(template_id: str) -> Optional[dict[str, Any]]:
    """Return the in-code template dict for ``template_id`` or None."""
    for spec in TEMPLATES:
        if spec["id"] == template_id:
            return spec
    return None


def template_exists(db: Session, template_id: str) -> bool:
    """True if ``template_id`` is a known template (DB row or in-code spec)."""
    if not template_id:
        return False
    if db.get(TemplateModel, template_id) is not None:
        return True
    return get_template_spec(template_id) is not None


def load_template_dict(db: Session, template_id: str) -> Optional[dict[str, Any]]:
    """Load a template as a plain dict (DB first, in-code fallback)."""
    row = db.get(TemplateModel, template_id)
    if row is not None:
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "tags": list(row.tags_json or []),
            "team": list(row.team_json or []),
            "planner_prompt": row.planner_prompt,
            "sample_mission": row.sample_mission,
            "expected_dag": list(row.expected_dag_json or []),
            "report_outline": list(row.report_outline_json or []),
        }
    return get_template_spec(template_id)
