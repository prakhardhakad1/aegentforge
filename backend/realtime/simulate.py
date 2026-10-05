"""Offline demo simulator — SimulatedRunPlayer (Agent 7).

Drives a FULL, realistic scripted run for demo mode (``RUN_MODE=demo``): a
planner → researcher → analyst ×2 → forecaster → critic pipeline that streams
pinned envelope events with natural pacing, **no LLM, no network, fully
deterministic** content (seeded PRNG + fixed scripts).

Honesty (repo rule): every payload that carries simulated analysis is labeled
``"simulated": True``, and all *numbers* are the measured facts of the bundled
sample datasets (``data/samples/*.csv``; see ``data/samples/EXPECTED_INSIGHTS.md``
— saas churn 24.8% overall / basic 37.4% vs pro 15.5% vs enterprise 7.6% /
median logins 13 churned vs 42 active; ecommerce Nov+Dec 27.1% of revenue /
mobile 33%→44% / returns 7.9%; support billing+login_bug 56% of volume /
integration 3.2x median resolution / response 5.3h→7.6h; marketing signups/$
email 1.011 > search 0.388 > content 0.321 > referral 0.273 > social 0.034).
The demo replays those measured sample stories — it never invents metrics.

Event flow (pinned envelope, seq starts at 1)::

    run_started
    plan_created                  {subtasks: [{id,title,agent,depends_on,status}]}
    ┆ per subtask (DAG order):
    │   agent_started             {subtask_id, title}
    │   thought_summary           {subtask_id, summary}
    │   tool_call / tool_result   {subtask_id, tool, args_summary, ok}
    │   artifact_created?         {subtask_id, artifact_id, kind, name,
    │                              summary, data?}  ← data = ChartSpec /
    │                              TableData / report dict (Agent 7 ext.)
    │   step_completed            {subtask_id}
    │   agent_finished            {subtask_id}
    │   token_update              {agent, input_tokens, output_tokens,
    │                              cost_usd, run_total_usd}
    run_finished                  {report_ready: true}

Pacing: ~25–45 s wall-clock at ``speed=1.0`` (≈33 s for the canonical
6-subtask plan); ``speed`` divides every delay and ``speed<=0`` plays
instantly. Determinism: delays and micro-variation come from a PRNG seeded
from (mission, template) — two runs with the same mission produce identical
content (timestamps and run_id excepted).

Backend wiring (``app/services/runner.py``): construct
``SimulatedRunPlayer(mission=..., run_id=..., template=..., template_id=...,
dataset_info=..., on_event=emitter.sync_sink())`` and ``await player.play()``.
Standalone use: :func:`run_simulation`.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from realtime.events import (
    AGENT_ROLES,
    EVENT_TYPES,
    make_event,
    utc_now_iso,
)
from realtime.token_meter import TokenMeter

__all__ = [
    "SIMULATION_SEED",
    "SIM_SPEED_INSTANT",
    "SimulatedRunPlayer",
    "auto_select_template",
    "resolve_story_key",
    "run_simulation",
]

#: Deterministic default PRNG seed (matches the sample-data generation seed).
SIMULATION_SEED: int = 20261005

#: Speed value meaning "no artificial delays" (also any speed <= 0).
SIM_SPEED_INSTANT: float = 1_000_000.0

OnEvent = Callable[[dict], None]

# ── Paced delays (seconds at speed=1.0, before deterministic jitter) ─────

BASE_DELAYS: dict[str, float] = {
    "run_started": 0.5,
    "plan_created": 1.0,
    "agent_started": 0.5,
    "thought_summary": 0.9,
    "tool_call": 0.7,
    "tool_result": 0.9,
    "artifact_created": 0.6,
    "step_completed": 0.35,
    "agent_finished": 0.3,
    "token_update": 0.2,
    "inter_subtask": 0.45,
    "pre_finish": 0.8,
}

#: Sleeps shorter than this are skipped entirely (keeps tests instant).
MIN_SLEEP_SECONDS: float = 0.005

# ── Template auto-selection keywords ─────────────────────────────────────

_TEMPLATE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "market_research_team": (
        "market", "marketing", "campaign", "channel", "channels", "spend",
        "budget", "advertising", "ads", "brand", "competitor", "competitors",
        "segment", "segments", "survey", "acquisition", "positioning",
        "audience", "promotion", "pricing page",
    ),
    "sales_insights_team": (
        "sales", "revenue", "churn", "retention", "ecommerce", "e-commerce",
        "orders", "order", "aov", "conversion", "returns", "upsell",
        "cross-sell", "pipeline", "subscription", "mrr", "arr", "customers",
        "customers", "shop", "store", "retail", "cart",
    ),
    "support_triage_team": (
        "support", "ticket", "tickets", "csat", "sla", "triage", "backlog",
        "queue", "resolution", "response time", "helpdesk", "help desk",
        "billing", "login", "bug", "onboarding tickets", "service desk",
    ),
}

_STORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "saas_churn": (
        "churn", "retention", "subscription", "saas", "cancel", "canceled",
        "cancelled", "renew", "renewal", "logins", "usage", "plan tier",
        "monthly_price", "tenure",
    ),
    "ecommerce_sales": (
        "ecommerce", "e-commerce", "order", "orders", "return", "returns",
        "category", "categories", "aov", "revenue", "shop", "store", "retail",
        "cart", "channel", "mobile", "holiday", "q4",
    ),
    "support_tickets": (
        "ticket", "tickets", "support", "csat", "sla", "response", "triage",
        "backlog", "queue", "resolution", "billing", "login", "bug",
    ),
    "marketing_spend": (
        "marketing", "channel", "channels", "spend", "signups", "campaign",
        "budget", "email", "search", "social", "content", "referral",
        "advertising",
    ),
}

TEMPLATE_IDS: tuple[str, ...] = (
    "market_research_team",
    "sales_insights_team",
    "support_triage_team",
)


def _keyword_score(text: str, keywords: Sequence[str]) -> int:
    """Count case-insensitive keyword occurrences in ``text``."""
    lowered = text.lower()
    return sum(lowered.count(keyword) for keyword in keywords)


def auto_select_template(mission: str) -> str:
    """Pick the pinned template id whose keywords best match ``mission``.

    Ties / zero scores deterministically resolve to ``market_research_team``.
    """
    best_id, best_score = "market_research_team", -1
    for template_id in TEMPLATE_IDS:
        score = _keyword_score(mission, _TEMPLATE_KEYWORDS[template_id])
        if score > best_score:
            best_id, best_score = template_id, score
    return best_id


def resolve_story_key(template_id: Optional[str], mission: str) -> str:
    """Resolve which sample-dataset story the run should tell.

    Rules (deterministic):
      * mission keywords always get a vote (they can override the template
        default so "churn" missions tell the churn story even under a
        different template);
      * ``market_research_team`` / ``support_triage_team`` default to their
        matching datasets;
      * ``sales_insights_team`` disambiguates churn vs ecommerce keywords.
    """
    story_scores = {
        key: _keyword_score(mission, keywords)
        for key, keywords in _STORY_KEYWORDS.items()
    }
    best_story = max(story_scores, key=lambda k: (story_scores[k], k))
    if story_scores[best_story] > 0:
        return best_story
    template_defaults = {
        "market_research_team": "marketing_spend",
        "sales_insights_team": "saas_churn",
        "support_triage_team": "support_tickets",
    }
    return template_defaults.get(template_id or "", "saas_churn")


# ── Script content model ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolStep:
    """One tool_call/tool_result pair."""

    tool: str
    args_summary: str
    result_summary: str


@dataclass(frozen=True)
class ArtifactDraft:
    """One artifact_created payload (minus ids/subtask linkage)."""

    kind: str
    name: str
    summary: str
    data: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class SubtaskScript:
    """Everything one subtask's agent says/does (content only, no ids)."""

    thought: str
    tools: tuple[ToolStep, ...] = ()
    artifacts: tuple[ArtifactDraft, ...] = ()


@dataclass(frozen=True)
class Story:
    """A full scripted run storyline grounded in one sample dataset."""

    key: str
    dataset: str
    rows: int
    columns: tuple[str, ...]
    mission_theme: str
    # agent role -> one script per canonical subtask of that agent, in order
    scripts: dict[str, tuple[SubtaskScript, ...]] = field(default_factory=dict)
    insights: tuple[dict[str, Any], ...] = ()
    predictions: tuple[dict[str, Any], ...] = ()
    recommendations: tuple[dict[str, Any], ...] = ()


# ── Canonical DAG per template ───────────────────────────────────────────


def _node(node_id: str, title: str, agent: str, depends_on: tuple[str, ...] = ()) -> dict:
    return {
        "id": node_id,
        "title": title,
        "agent": agent,
        "depends_on": list(depends_on),
        "status": "pending",
    }


CANONICAL_PLANS: dict[str, list[dict[str, Any]]] = {
    "market_research_team": [
        _node("st1", "Frame the market question and work plan", "planner"),
        _node("st2", "Gather external context and channel benchmarks", "researcher", ("st1",)),
        _node("st3", "Profile channel spend and signup efficiency", "analyst", ("st1",)),
        _node("st4", "Deep-dive the fastest-improving channel", "analyst", ("st3",)),
        _node("st5", "Project the impact of reallocating budget", "forecaster", ("st3", "st4")),
        _node("st6", "Stress-test claims and rank recommendations", "critic", ("st2", "st3", "st4", "st5")),
    ],
    "sales_insights_team": [
        _node("st1", "Frame the revenue question and work plan", "planner"),
        _node("st2", "Gather retention and revenue context", "researcher", ("st1",)),
        _node("st3", "Profile churn and revenue drivers", "analyst", ("st1",)),
        _node("st4", "Segment the highest-risk and highest-value groups", "analyst", ("st3",)),
        _node("st5", "Project the near-term trend", "forecaster", ("st3", "st4")),
        _node("st6", "Stress-test findings and rank recommendations", "critic", ("st2", "st3", "st4", "st5")),
    ],
    "support_triage_team": [
        _node("st1", "Frame the support-operations question and work plan", "planner"),
        _node("st2", "Gather support benchmarks and triage context", "researcher", ("st1",)),
        _node("st3", "Profile ticket volume by category", "analyst", ("st1",)),
        _node("st4", "Analyze resolution and response-time trends", "analyst", ("st3",)),
        _node("st5", "Project response times under current staffing", "forecaster", ("st3", "st4")),
        _node("st6", "Stress-test findings and rank recommendations", "critic", ("st2", "st3", "st4", "st5")),
    ],
}

DEFAULT_TEMPLATE_ID = "market_research_team"


def _chart(chart_id: str, kind: str, title: str, x_label: str, y_label: str,
           data: list[dict[str, Any]], notes: str) -> dict[str, Any]:
    from realtime.events import chart_spec

    return chart_spec(chart_id, kind, title, x_label, y_label, data, notes=notes)


# ── The four measured sample-dataset stories ─────────────────────────────
# Every number below is measured on data/samples/*.csv (EXPECTED_INSIGHTS.md).


def _saas_churn_story() -> Story:
    return Story(
        key="saas_churn",
        dataset="saas_churn.csv",
        rows=2_000,
        columns=("customer_id", "signup_date", "plan", "monthly_price", "region",
                 "months_active", "logins_last_30d", "tickets_raised", "is_churned"),
        mission_theme="customer churn",
        scripts={
            "planner": (
                SubtaskScript(
                    thought=(
                        "This is a churn-diagnosis mission: I'll split it into data "
                        "analysis on the customer base, external context, a forward "
                        "look, and a critic pass before recommendations."
                    ),
                    tools=(
                        ToolStep(
                            "plan_dag",
                            "decompose mission into a 6-node DAG across 5 specialist roles",
                            "DAG with 6 subtasks; analyst deep-dive depends on the base profile",
                        ),
                    ),
                ),
            ),
            "researcher": (
                SubtaskScript(
                    thought=(
                        "I'll pull common churn-driver patterns so the analyst knows "
                        "which segments matter; no live web search runs in demo mode, "
                        "these are simulated context notes."
                    ),
                    tools=(
                        ToolStep(
                            "web_search",
                            'queries: "SaaS churn benchmarks by plan tier", "login activity churn signal"',
                            "found recurring patterns: collapsing usage precedes cancellation; entry-tier plans churn hardest",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "text",
                            "churn_context_notes",
                            (
                                "Simulated research notes (demo, no live search): "
                                "typical churn investigations weigh plan tier, usage decay, "
                                "support friction and tenure. The dataset story below is "
                                "measured on the bundled sample saas_churn.csv."
                            ),
                            {
                                "markdown": (
                                    "## Context notes (simulated)\n\n"
                                    "- Usage decay (logins_last_30d) is the classic leading "
                                    "indicator of cancellation.\n"
                                    "- Entry-tier month-to-month plans usually churn hardest.\n"
                                    "- Support friction correlates with churn in most SaaS bases.\n\n"
                                    "_Demo mode: no live web search ran; content is a simulated "
                                    "brief grounded in the bundled sample dataset._"
                                )
                            },
                        ),
                    ),
                ),
            ),
            "analyst": (
                SubtaskScript(
                    thought=(
                        "First pass: overall churn and the split by plan tier. I expect "
                        "the basic tier to dominate the churn pool."
                    ),
                    tools=(
                        ToolStep(
                            "csv_analyzer",
                            "group saas_churn.csv (2,000 rows) by plan; aggregate mean(is_churned)",
                            "overall churn 24.8% (496/2,000); basic 37.4%, pro 15.5%, enterprise 7.6%",
                        ),
                        ToolStep(
                            "chart",
                            "render churn rate by plan as a bar chart",
                            "bar chart with 3 points rendered",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "chart",
                            "churn_rate_by_plan",
                            "Basic-plan customers churn at 37.4% — about 2.4x the pro rate "
                            "and ~4.9x enterprise — pulling the blended rate to 24.8%.",
                            data=_chart(
                                "chart_churn_by_plan", "bar",
                                "Churn rate by plan (%)",
                                "plan", "churn rate (%)",
                                [
                                    {"label": "basic", "x": 1, "y": 37.4},
                                    {"label": "pro", "x": 2, "y": 15.5},
                                    {"label": "enterprise", "x": 3, "y": 7.6},
                                ],
                                notes="Measured on data/samples/saas_churn.csv (2,000 customers).",
                            ),
                        ),
                    ),
                ),
                SubtaskScript(
                    thought=(
                        "Now the usage signal: compare login activity for churned vs "
                        "active customers and the churn rate inside usage bands."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "median logins_last_30d by is_churned; churn rate for <5 and 30+ login bands",
                            "median logins 13 (churned) vs 42 (active); <5 logins → 51.0% churn; 30+ → 1.5%",
                        ),
                        ToolStep(
                            "chart",
                            "tabulate usage-band churn rates",
                            "summary table built",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "table",
                            "usage_signal_by_band",
                            "Collapsing usage precedes cancellation: churned customers median "
                            "13 logins vs 42 for active; under 5 logins churn at 51.0%, 30+ "
                            "logins at just 1.5%.",
                            data={
                                "columns": ["segment", "median_logins_last_30d", "churn_rate_pct"],
                                "rows": [
                                    ["churned customers", 13, None],
                                    ["active customers", 42, None],
                                    ["fewer than 5 logins", None, 51.0],
                                    ["30+ logins", None, 1.5],
                                ],
                            },
                        ),
                    ),
                ),
            ),
            "forecaster": (
                SubtaskScript(
                    thought=(
                        "I'll score churn risk from the two strongest signals — plan tier "
                        "and login decay — and state confidence bands."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "churn probability by usage band; correlation logins_last_30d vs is_churned",
                            "corr -0.52; <5 logins ≈ 50% churn probability, 30+ ≈ 2%",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "prediction",
                            "churn_risk_prediction",
                            "A customer under 5 monthly logins carries roughly 50% churn "
                            "probability; 30+ logins is near-safe (~2%). Basic-plan + "
                            "declining-usage is the at-risk core.",
                            data={
                                "claim": (
                                    "Customers with <5 logins in their last month have ~50% "
                                    "churn probability; customers with 30+ logins ~2%."
                                ),
                                "confidence": 0.86,
                                "basis": (
                                    "Measured churn within usage bands on saas_churn.csv "
                                    "(51.0% for <5 logins, 1.5% for 30+); correlation of "
                                    "logins_last_30d with churn -0.52."
                                ),
                            },
                        ),
                    ),
                ),
            ),
            "critic": (
                SubtaskScript(
                    thought=(
                        "The plan-tier and usage claims are strongly evidenced; the "
                        "support-friction angle is weaker (2.5 vs 1.0 tickets) — I'll rank "
                        "recommendations by expected impact and effort."
                    ),
                    tools=(
                        ToolStep(
                            "claim_check",
                            "verify each insight against the measured stats",
                            "2 claims high-strength, 1 medium; no unsupported claims remain",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "recommendation",
                            "ranked_churn_recommendations",
                            "Three ranked moves: usage-triggered save offers, early-tenure "
                            "onboarding, and annual-commitment conversion for basic plans.",
                            data={
                                "recommendations": [
                                    {
                                        "title": "Trigger save offers on usage decay",
                                        "action": (
                                            "When a pro/basic customer's logins drop below "
                                            "~15/month, fire an in-app check-in or discount."
                                        ),
                                        "expected_impact": "Catches the 51%-churn <5-login band before cancel",
                                        "effort": "M",
                                        "priority": 1,
                                    },
                                    {
                                        "title": "Push onboarding in the first 2 months",
                                        "action": "Guided setup + usage nudges for new basic/pro accounts.",
                                        "expected_impact": "Reduces early-tenure churn hazard",
                                        "effort": "S",
                                        "priority": 2,
                                    },
                                    {
                                        "title": "Move basic plans to annual commitments",
                                        "action": "Discounted annual upgrade offer for month-to-month basic customers.",
                                        "expected_impact": "Basic churns at 37.4% vs enterprise 7.6% — commitment helps",
                                        "effort": "M",
                                        "priority": 3,
                                    },
                                ],
                            },
                        ),
                        ArtifactDraft(
                            "report_markdown",
                            "churn_report",
                            "Final simulated report: churn is concentrated in the basic tier "
                            "and in collapsing login activity; three ranked fixes.",
                            data={"markdown": ""},  # filled by _report_markdown()
                        ),
                    ),
                ),
            ),
        },
        insights=(
            {
                "title": "Churn concentrates in the basic tier",
                "detail": (
                    "Basic-plan customers churn at 37.4% vs 15.5% (pro) and 7.6% "
                    "(enterprise) — ~2.4x–4.9x the other tiers — driving the blended "
                    "24.8% rate."
                ),
                "evidence": ["churn by plan measured on saas_churn.csv (n=2,000)"],
                "strength": "high",
            },
            {
                "title": "Collapsing usage precedes cancellation",
                "detail": (
                    "Median logins_last_30d is 13 for churned vs 42 for active "
                    "customers (correlation -0.52); <5 logins churn at 51.0%, 30+ "
                    "logins at 1.5%."
                ),
                "evidence": ["usage-band churn rates measured on the sample"],
                "strength": "high",
            },
            {
                "title": "Churned customers lean on support",
                "detail": "Churned customers raised ~2.4x more tickets (2.5 vs 1.0 on average).",
                "evidence": ["tickets_raised means by churn outcome"],
                "strength": "medium",
            },
        ),
        predictions=(
            {
                "claim": "Customers with <5 monthly logins have ~50% churn probability.",
                "confidence": 0.86,
                "basis": "51.0% measured churn in the <5-login band; 30+ logins ≈ 1.5%.",
            },
        ),
        recommendations=(
            {
                "title": "Trigger save offers on usage decay",
                "action": "In-app check-in or discount when logins fall below ~15/month.",
                "expected_impact": "Intercepts the 51%-churn low-usage band",
                "effort": "M",
                "priority": 1,
            },
            {
                "title": "Invest in first-2-month onboarding",
                "action": "Guided setup and usage nudges for new accounts.",
                "expected_impact": "Reduces early-tenure churn hazard",
                "effort": "S",
                "priority": 2,
            },
            {
                "title": "Convert basic plans to annual",
                "action": "Discounted annual upgrade for month-to-month basic customers.",
                "expected_impact": "Basic churn 37.4% is the single biggest leak",
                "effort": "M",
                "priority": 3,
            },
        ),
    )


def _ecommerce_sales_story() -> Story:
    return Story(
        key="ecommerce_sales",
        dataset="ecommerce_sales.csv",
        rows=5_000,
        columns=("order_id", "order_date", "product_category", "product_name",
                 "region", "channel", "quantity", "unit_price", "revenue",
                 "is_returned"),
        mission_theme="revenue and channel mix",
        scripts={
            "planner": (
                SubtaskScript(
                    thought=(
                        "Revenue diagnosis on order data: I'll schedule a base profile "
                        "of seasonality and channels, a category deep-dive, then a "
                        "forecast and a critic pass."
                    ),
                    tools=(
                        ToolStep(
                            "plan_dag",
                            "decompose mission into a 6-node DAG across 5 specialist roles",
                            "DAG with 6 subtasks; forecast depends on both analyst passes",
                        ),
                    ),
                ),
            ),
            "researcher": (
                SubtaskScript(
                    thought=(
                        "I'll assemble the retail context the analyst should test — "
                        "holiday seasonality and channel shift — as simulated notes."
                    ),
                    tools=(
                        ToolStep(
                            "web_search",
                            'queries: "ecommerce Q4 holiday revenue share", "mobile share of orders trend"',
                            "patterns found: Q4 concentration; mobile share rising year over year",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "text",
                            "retail_context_notes",
                            (
                                "Simulated research notes (demo, no live search): Q4 "
                                "holiday concentration and rising mobile share are the two "
                                "forces to verify in the order data."
                            ),
                            {
                                "markdown": (
                                    "## Context notes (simulated)\n\n"
                                    "- Q4 (Nov+Dec) typically concentrates a large share of "
                                    "annual revenue for retail.\n"
                                    "- Mobile's share of orders keeps climbing at the expense "
                                    "of web.\n\n"
                                    "_Demo mode: no live web search ran; grounded in the "
                                    "bundled sample ecommerce_sales.csv._"
                                )
                            },
                        ),
                    ),
                ),
            ),
            "analyst": (
                SubtaskScript(
                    thought=(
                        "First pass: revenue seasonality and channel mix. I expect a "
                        "strong Nov+Dec spike and mobile taking share."
                    ),
                    tools=(
                        ToolStep(
                            "csv_analyzer",
                            "aggregate ecommerce_sales.csv (5,000 rows) revenue by month and by channel",
                            "revenue $0.75M total, AOV $149.33; Nov+Dec = 27.1% of revenue; mobile share 33%→44%",
                        ),
                        ToolStep(
                            "chart",
                            "render holiday revenue concentration as a pie chart",
                            "pie chart with 2 points rendered",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "chart",
                            "holiday_revenue_concentration",
                            "November and December alone deliver 27.1% of annual revenue "
                            "($121k in December vs ~$55k in a typical month).",
                            data=_chart(
                                "chart_q4_share", "pie",
                                "Revenue concentration: Nov+Dec vs rest of year",
                                "window", "share of revenue (%)",
                                [
                                    {"label": "Nov+Dec 2025", "x": 1, "y": 27.1},
                                    {"label": "Rest of year", "x": 2, "y": 72.9},
                                ],
                                notes="Measured on data/samples/ecommerce_sales.csv (5,000 orders, 2025-10 → 2026-09).",
                            ),
                        ),
                    ),
                ),
                SubtaskScript(
                    thought=(
                        "Deep-dive categories and returns: which category is fading and "
                        "where margin leaks through returns."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "orders/month trend by product_category; return rate by category",
                            "books -62% (~42→~16 orders/month); returns 7.9% overall, apparel 12.0%, books 1.8%",
                        ),
                        ToolStep(
                            "chart",
                            "build the category watchlist table",
                            "summary table built",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "table",
                            "category_watchlist",
                            "Books is structurally declining (-62% order volume) while "
                            "apparel's 12.0% return rate — ~4x books' 1.8% — erodes margin.",
                            data={
                                "columns": ["category", "metric", "value", "context"],
                                "rows": [
                                    ["books", "order volume trend", "-62%", "~42 → ~16 orders/month"],
                                    ["apparel", "return rate", "12.0%", "worst category"],
                                    ["books", "return rate", "1.8%", "best category"],
                                    ["all categories", "return rate", "7.9%", "overall"],
                                ],
                            },
                        ),
                    ),
                ),
            ),
            "forecaster": (
                SubtaskScript(
                    thought=(
                        "Projection: hold the non-Q4 run rate, add the Q4 spike, and "
                        "extend the mobile-share trend."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "monthly revenue run-rate extrapolation; mobile share linear trend",
                            "next quarter ≈ $60-70k/month outside Q4; mobile majority within ~2 quarters",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "prediction",
                            "revenue_outlook",
                            "Next quarter lands near the September-2026 run rate "
                            "(~$60-70k/month) outside Q4; mobile becomes the majority "
                            "channel within ~2 quarters at the current trend.",
                            data={
                                "claim": (
                                    "Non-Q4 monthly revenue holds around $60-70k and mobile "
                                    "reaches >50% of orders within ~2 quarters."
                                ),
                                "confidence": 0.78,
                                "basis": (
                                    "Sep-2026 run rate on ecommerce_sales.csv and the mobile "
                                    "share trend 33%→44% (Q4 2025 → Q3 2026)."
                                ),
                            },
                        ),
                    ),
                ),
            ),
            "critic": (
                SubtaskScript(
                    thought=(
                        "Seasonality and channel-shift claims are strongly evidenced; the "
                        "books decline is a structural call, so I'll rank actions by "
                        "impact and reversibility."
                    ),
                    tools=(
                        ToolStep(
                            "claim_check",
                            "verify each insight against the measured stats",
                            "3 claims high-strength, 1 medium; no unsupported claims remain",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "recommendation",
                            "ranked_revenue_recommendations",
                            "Three ranked moves: mobile experience before Q4, apparel "
                            "returns audit, and repositioning the books category.",
                            data={
                                "recommendations": [
                                    {
                                        "title": "Double down on mobile before Q4",
                                        "action": "Invest in mobile UX/conversion ahead of the Nov+Dec peak.",
                                        "expected_impact": "Mobile is 44% of orders and growing — the Q4 engine runs through it",
                                        "effort": "M",
                                        "priority": 1,
                                    },
                                    {
                                        "title": "Audit apparel sizing and returns",
                                        "action": "Inspect sizing/quality drivers behind the 12.0% return rate.",
                                        "expected_impact": "Returns erode margin; apparel is ~4x the best-category rate",
                                        "effort": "M",
                                        "priority": 2,
                                    },
                                    {
                                        "title": "Sunset or reposition books",
                                        "action": "Reallocate books' shelf/marketing to beauty and home.",
                                        "expected_impact": "Books volume is down 62% with no stabilizing signal",
                                        "effort": "S",
                                        "priority": 3,
                                    },
                                ],
                            },
                        ),
                        ArtifactDraft(
                            "report_markdown",
                            "revenue_report",
                            "Final simulated report: Q4 is the revenue engine, mobile is "
                            "taking over, books is fading; three ranked fixes.",
                            data={"markdown": ""},  # filled by _report_markdown()
                        ),
                    ),
                ),
            ),
        },
        insights=(
            {
                "title": "Q4 is the revenue engine",
                "detail": (
                    "November+December contribute 27.1% of annual revenue; December "
                    "alone is $121k vs a ~$55k typical month."
                ),
                "evidence": ["monthly revenue aggregation on ecommerce_sales.csv (n=5,000)"],
                "strength": "high",
            },
            {
                "title": "Mobile is taking the channel mix",
                "detail": "Mobile grows from ~33% to ~44% of orders (Q4 2025 → Q3 2026) while web declines.",
                "evidence": ["channel share by quarter"],
                "strength": "high",
            },
            {
                "title": "Books is structurally declining",
                "detail": "Books order volume fell ~62% (~42 → ~16 orders/month); every other category is stable or growing.",
                "evidence": ["per-category monthly order trend"],
                "strength": "high",
            },
            {
                "title": "Apparel returns erode margin",
                "detail": "Overall return rate is 7.9%; apparel is 12.0% — about 4x books' 1.8%.",
                "evidence": ["return rate by category"],
                "strength": "medium",
            },
        ),
        predictions=(
            {
                "claim": "Non-Q4 revenue holds around $60-70k/month; Q4 spikes on top.",
                "confidence": 0.78,
                "basis": "Sep-2026 run rate and the measured Nov+Dec 27.1% concentration.",
            },
        ),
        recommendations=(
            {
                "title": "Invest in mobile UX before Q4",
                "action": "Conversion and checkout work on the fastest-growing channel.",
                "expected_impact": "Mobile at 44% share and rising drives the Q4 peak",
                "effort": "M",
                "priority": 1,
            },
            {
                "title": "Audit apparel returns",
                "action": "Sizing/quality investigation on the 12.0% return rate.",
                "expected_impact": "Direct margin recovery",
                "effort": "M",
                "priority": 2,
            },
            {
                "title": "Reposition the books category",
                "action": "Sunset or reallocate books shelf/marketing to beauty and home.",
                "expected_impact": "Stops the -62% decline from consuming resources",
                "effort": "S",
                "priority": 3,
            },
        ),
    )


def _support_tickets_story() -> Story:
    return Story(
        key="support_tickets",
        dataset="support_tickets.csv",
        rows=1_500,
        columns=("ticket_id", "created_date", "category", "priority", "subject",
                 "first_response_hours", "resolution_hours", "is_resolved", "csat"),
        mission_theme="support triage",
        scripts={
            "planner": (
                SubtaskScript(
                    thought=(
                        "Support-operations mission: profile the volume mix first, then "
                        "resolution/response trends, then a staffing projection and a "
                        "critic pass."
                    ),
                    tools=(
                        ToolStep(
                            "plan_dag",
                            "decompose mission into a 6-node DAG across 5 specialist roles",
                            "DAG with 6 subtasks; response-time forecast depends on both analyst passes",
                        ),
                    ),
                ),
            ),
            "researcher": (
                SubtaskScript(
                    thought=(
                        "I'll gather triage heuristics to test against the data — "
                        "deflection for repetitive categories, specialist pods for "
                        "complex ones — as simulated notes."
                    ),
                    tools=(
                        ToolStep(
                            "web_search",
                            'queries: "support ticket category triage strategy", "first response SLA benchmarks"',
                            "patterns found: self-service deflection for billing/login; specialist queues for complex categories",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "text",
                            "support_context_notes",
                            (
                                "Simulated research notes (demo, no live search): "
                                "self-service deflection suits high-volume repetitive "
                                "categories; complex categories need specialist queues."
                            ),
                            {
                                "markdown": (
                                    "## Context notes (simulated)\n\n"
                                    "- Billing and login issues are the classic deflection "
                                    "candidates (repetitive, scriptable).\n"
                                    "- Complex integration work needs a dedicated queue to "
                                    "protect the general SLA.\n\n"
                                    "_Demo mode: no live web search ran; grounded in the "
                                    "bundled sample support_tickets.csv._"
                                )
                            },
                        ),
                    ),
                ),
            ),
            "analyst": (
                SubtaskScript(
                    thought=(
                        "First pass: where does volume come from? I expect two "
                        "categories to dominate the queue."
                    ),
                    tools=(
                        ToolStep(
                            "csv_analyzer",
                            "group support_tickets.csv (1,500 rows) by category; share of volume",
                            "billing 31% + login_bug 25% = 56% of volume; how_to 18%, feature_request 15%, integration 11%",
                        ),
                        ToolStep(
                            "chart",
                            "render volume share by category as a bar chart",
                            "bar chart with 5 points rendered",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "chart",
                            "ticket_volume_by_category",
                            "Billing (31%) and login bugs (25%) together consume 56% of "
                            "support capacity — the clearest automation target.",
                            data=_chart(
                                "chart_ticket_volume", "bar",
                                "Ticket volume share by category (%)",
                                "category", "share of tickets (%)",
                                [
                                    {"label": "billing", "x": 1, "y": 31.0},
                                    {"label": "login_bug", "x": 2, "y": 25.0},
                                    {"label": "how_to", "x": 3, "y": 18.0},
                                    {"label": "feature_request", "x": 4, "y": 15.0},
                                    {"label": "integration", "x": 5, "y": 11.0},
                                ],
                                notes="Measured on data/samples/support_tickets.csv (1,500 tickets, 2025-10 → 2026-09).",
                            ),
                        ),
                    ),
                ),
                SubtaskScript(
                    thought=(
                        "Now speed and quality: resolution times by category, the "
                        "response-time trend, and how CSAT moves with them."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "median first_response_hours by quarter; median resolution_hours by category; corr(resolution_hours, csat)",
                            "integration median 32.5h vs 10.0h others (3.2x); response 5.3h→7.6h (+43%); corr(csat) -0.27",
                        ),
                        ToolStep(
                            "chart",
                            "build the speed-and-quality table",
                            "summary table built",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "table",
                            "speed_and_quality",
                            "Integration tickets take 3.2x longer to resolve (32.5h vs "
                            "10.0h median), and first response worsened 5.3h → 7.6h in "
                            "the recent months; slower resolution tracks lower CSAT.",
                            data={
                                "columns": ["metric", "value", "context"],
                                "rows": [
                                    ["median first response (first quarter)", "5.3h", "start of window"],
                                    ["median first response (last 3 months)", "7.6h", "+43%"],
                                    ["median resolution — integration", "32.5h", "3.2x all other categories"],
                                    ["median resolution — all others", "10.0h", ""],
                                    ["unresolved tickets", "11.9%", "CSAT present only for resolved"],
                                    ["resolution vs CSAT", "-0.27", "correlation"],
                                ],
                            },
                        ),
                    ),
                ),
            ),
            "forecaster": (
                SubtaskScript(
                    thought=(
                        "Projection: extend the response-time trend under current "
                        "staffing and state the integration-queue risk."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "first_response_hours trend extrapolation; integration resolution distribution",
                            "next-month median response ≈ 7.5-8h; integration tickets more likely than not to exceed 24h",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "prediction",
                            "support_outlook",
                            "Median first response lands around 7.5-8h next month unless "
                            "staffing changes; a new integration ticket is more likely "
                            "than not to take >24h to resolve.",
                            data={
                                "claim": (
                                    "Median first response next month ≈ 7.5-8h; integration "
                                    "tickets more likely than not exceed 24h resolution."
                                ),
                                "confidence": 0.74,
                                "basis": (
                                    "Response trend 5.3h → 7.6h across the window and the "
                                    "integration median of 32.5h on support_tickets.csv."
                                ),
                            },
                        ),
                    ),
                ),
            ),
            "critic": (
                SubtaskScript(
                    thought=(
                        "The volume and latency claims are strongly evidenced. I'll rank "
                        "recommendations by agent-hours freed and SLA recovery."
                    ),
                    tools=(
                        ToolStep(
                            "claim_check",
                            "verify each insight against the measured stats",
                            "3 claims high-strength, 1 medium; no unsupported claims remain",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "recommendation",
                            "ranked_support_recommendations",
                            "Three ranked moves: self-service billing tools, an "
                            "integrations specialist pod, and staffing/async routing to "
                            "restore the <6h SLA.",
                            data={
                                "recommendations": [
                                    {
                                        "title": "Ship self-service billing tools",
                                        "action": "Invoice download and card self-update to deflect the largest category.",
                                        "expected_impact": "Billing is 31% of volume — the biggest deflection win",
                                        "effort": "M",
                                        "priority": 1,
                                    },
                                    {
                                        "title": "Create an integrations specialist rotation",
                                        "action": "Dedicated pod for integration tickets.",
                                        "expected_impact": "Integration takes 3.2x longer and drags the shared queue",
                                        "effort": "S",
                                        "priority": 2,
                                    },
                                    {
                                        "title": "Restore the <6h response SLA",
                                        "action": "Staff up or route low-priority tickets async.",
                                        "expected_impact": "Response times worsened 43% to 7.6h — recovery needs capacity",
                                        "effort": "M",
                                        "priority": 3,
                                    },
                                ],
                            },
                        ),
                        ArtifactDraft(
                            "report_markdown",
                            "support_report",
                            "Final simulated report: two categories eat half the queue, "
                            "integrations need their own pod, and the response SLA is "
                            "slipping; three ranked fixes.",
                            data={"markdown": ""},  # filled by _report_markdown()
                        ),
                    ),
                ),
            ),
        },
        insights=(
            {
                "title": "Two categories eat half the queue",
                "detail": "Billing (31%) + login_bug (25%) = 56% of all tickets — the prime automation target.",
                "evidence": ["volume share by category on support_tickets.csv (n=1,500)"],
                "strength": "high",
            },
            {
                "title": "Integrations are a queue of their own",
                "detail": "Integration tickets take 3.2x longer to resolve (median 32.5h vs 10.0h for everything else).",
                "evidence": ["median resolution_hours by category"],
                "strength": "high",
            },
            {
                "title": "Response SLA is degrading",
                "detail": "Median first response worsened from 5.3h to 7.6h (+43%) across the window.",
                "evidence": ["first_response_hours by quarter"],
                "strength": "high",
            },
            {
                "title": "Slower resolution hurts satisfaction",
                "detail": "Resolution time correlates with CSAT at -0.27; how_to scores best (4.57), billing worst (3.62).",
                "evidence": ["csat correlation and per-category means"],
                "strength": "medium",
            },
        ),
        predictions=(
            {
                "claim": "Median first response next month lands around 7.5-8h without staffing changes.",
                "confidence": 0.74,
                "basis": "Linear extension of the 5.3h → 7.6h response-time trend.",
            },
        ),
        recommendations=(
            {
                "title": "Self-service billing tools",
                "action": "Invoice download, card self-update, plan-change flows.",
                "expected_impact": "Deflects the largest category (31%)",
                "effort": "M",
                "priority": 1,
            },
            {
                "title": "Integrations specialist pod",
                "action": "Dedicated rotation for integration tickets.",
                "expected_impact": "Contains the 3.2x-resolution-time category",
                "effort": "S",
                "priority": 2,
            },
            {
                "title": "Recover the <6h response SLA",
                "action": "Staff up or route low-priority tickets async.",
                "expected_impact": "Reverses the 43% response-time degradation",
                "effort": "M",
                "priority": 3,
            },
        ),
    )


def _marketing_spend_story() -> Story:
    return Story(
        key="marketing_spend",
        dataset="marketing_spend.csv",
        rows=800,
        columns=("week_start_date", "channel", "spend", "impressions", "clicks",
                 "signups", "conversions"),
        mission_theme="marketing channel efficiency",
        scripts={
            "planner": (
                SubtaskScript(
                    thought=(
                        "Channel-efficiency mission: I'll order a base efficiency "
                        "profile, a compounding-trend deep-dive, a reallocation "
                        "projection, then a critic pass."
                    ),
                    tools=(
                        ToolStep(
                            "plan_dag",
                            "decompose mission into a 6-node DAG across 5 specialist roles",
                            "DAG with 6 subtasks; budget projection depends on both analyst passes",
                        ),
                    ),
                ),
            ),
            "researcher": (
                SubtaskScript(
                    thought=(
                        "I'll frame the benchmarks the analyst should compute — cost "
                        "per signup and per conversion by channel — as simulated notes."
                    ),
                    tools=(
                        ToolStep(
                            "web_search",
                            'queries: "marketing channel efficiency benchmarks", "content marketing compounding returns"',
                            "patterns found: efficiency varies an order of magnitude across channels; content compounds slowly",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "text",
                            "channel_context_notes",
                            (
                                "Simulated research notes (demo, no live search): channel "
                                "efficiency often differs ~10-30x, and content compounds "
                                "rather than converting immediately."
                            ),
                            {
                                "markdown": (
                                    "## Context notes (simulated)\n\n"
                                    "- Compare channels on signups-per-dollar, not raw "
                                    "volume.\n"
                                    "- Content channels typically compound with time as "
                                    "authority builds.\n\n"
                                    "_Demo mode: no live web search ran; grounded in the "
                                    "bundled sample marketing_spend.csv._"
                                )
                            },
                        ),
                    ),
                ),
            ),
            "analyst": (
                SubtaskScript(
                    thought=(
                        "First pass: efficiency by channel. I expect a wide spread "
                        "between the best and worst dollar."
                    ),
                    tools=(
                        ToolStep(
                            "csv_analyzer",
                            "aggregate marketing_spend.csv (800 rows) by channel; signups/spend and conversions/spend",
                            "signups/$: email 1.011 > search 0.388 > content 0.321 > referral 0.273 > social 0.034",
                        ),
                        ToolStep(
                            "chart",
                            "render signups-per-dollar by channel as a bar chart",
                            "bar chart with 5 points rendered",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "chart",
                            "signups_per_dollar_by_channel",
                            "Email returns 1.011 signups per dollar — ~30x social's 0.034; "
                            "search (0.388), content (0.321) and referral (0.273) sit in "
                            "between.",
                            data=_chart(
                                "chart_channel_efficiency", "bar",
                                "Signups per $1 spent by channel",
                                "channel", "signups per $1",
                                [
                                    {"label": "email", "x": 1, "y": 1.011},
                                    {"label": "search", "x": 2, "y": 0.388},
                                    {"label": "content", "x": 3, "y": 0.321},
                                    {"label": "referral", "x": 4, "y": 0.273},
                                    {"label": "social", "x": 5, "y": 0.034},
                                ],
                                notes="Measured on data/samples/marketing_spend.csv (800 rows, 5 channels x 160 weeks).",
                            ),
                        ),
                    ),
                ),
                SubtaskScript(
                    thought=(
                        "Deep-dive the trend: is any channel improving fast enough to "
                        "change the ranking within a year?"
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "content-channel signups/$ in the first vs last 20 weeks",
                            "content rose 0.242 → 0.380, overtaking referral",
                        ),
                        ToolStep(
                            "chart",
                            "render content efficiency trend as a line chart",
                            "line chart with 2 points rendered",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "chart",
                            "content_efficiency_trend",
                            "Content is compounding: signups-per-dollar rose from 0.242 "
                            "(first 20 weeks) to 0.380 (last 20 weeks), overtaking referral.",
                            data=_chart(
                                "chart_content_trend", "line",
                                "Content channel efficiency over time",
                                "window", "signups per $1",
                                [
                                    {"label": "first 20 weeks", "x": 1, "y": 0.242},
                                    {"label": "last 20 weeks", "x": 2, "y": 0.380},
                                ],
                                notes="First vs last 20-week windows of marketing_spend.csv.",
                            ),
                        ),
                    ),
                ),
            ),
            "forecaster": (
                SubtaskScript(
                    thought=(
                        "Projection: quantify a budget shift from the worst to the best "
                        "channel and the content trend's endpoint."
                    ),
                    tools=(
                        ToolStep(
                            "code_sandbox",
                            "incremental signups from shifting $100/week social → email at observed efficiencies",
                            "≈ +90 incremental signups/week; content becomes #2 within ~a year if trend holds",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "prediction",
                            "budget_shift_outlook",
                            "Shifting $100/week of social spend to email yields roughly "
                            "+90 incremental signups per week at observed efficiencies; "
                            "content becomes the #2 channel within about a year if its "
                            "trend holds.",
                            data={
                                "claim": (
                                    "Moving $100/week from social to email adds ~90 "
                                    "signups/week; content reaches #2 by signups/$ within "
                                    "a year."
                                ),
                                "confidence": 0.8,
                                "basis": (
                                    "Observed efficiencies email 1.011 vs social 0.034 "
                                    "signups/$; content trend 0.242 → 0.380."
                                ),
                            },
                        ),
                    ),
                ),
            ),
            "critic": (
                SubtaskScript(
                    thought=(
                        "The efficiency ranking is strongly evidenced; the content "
                        "projection assumes the trend holds. I'll rank by payback speed."
                    ),
                    tools=(
                        ToolStep(
                            "claim_check",
                            "verify each insight against the measured stats",
                            "3 claims high-strength, 1 medium; no unsupported claims remain",
                        ),
                    ),
                    artifacts=(
                        ArtifactDraft(
                            "recommendation",
                            "ranked_budget_recommendations",
                            "Three ranked moves: reallocate social to email/search, keep "
                            "funding compounding content, and cap social at a brand floor.",
                            data={
                                "recommendations": [
                                    {
                                        "title": "Reallocate social budget to email and search",
                                        "action": "Move most social spend to the two best-ROI channels.",
                                        "expected_impact": "Email returns ~30x social per dollar",
                                        "effort": "S",
                                        "priority": 1,
                                    },
                                    {
                                        "title": "Keep investing in content",
                                        "action": "Maintain or grow content spend — it compounds.",
                                        "expected_impact": "Efficiency rose 0.242 → 0.380 and overtook referral",
                                        "effort": "S",
                                        "priority": 2,
                                    },
                                    {
                                        "title": "Cap social at a brand-awareness floor",
                                        "action": "Hold social at ~its current minimum until conversion tracking improves.",
                                        "expected_impact": "Stops the weakest dollar (0.034 signups/$) from scaling",
                                        "effort": "S",
                                        "priority": 3,
                                    },
                                ],
                            },
                        ),
                        ArtifactDraft(
                            "report_markdown",
                            "channel_efficiency_report",
                            "Final simulated report: email and search are the efficient "
                            "engines, content compounds, social underperforms; three "
                            "ranked fixes.",
                            data={"markdown": ""},  # filled by _report_markdown()
                        ),
                    ),
                ),
            ),
        },
        insights=(
            {
                "title": "Email and search are the efficient engines",
                "detail": (
                    "Signups per $1: email 1.011, search 0.388, content 0.321, "
                    "referral 0.273, social 0.034 — a ~30x spread."
                ),
                "evidence": ["channel aggregation on marketing_spend.csv (n=800)"],
                "strength": "high",
            },
            {
                "title": "Content compounds",
                "detail": "Content's signups/$ rose from 0.242 (first 20 weeks) to 0.380 (last 20 weeks), overtaking referral.",
                "evidence": ["first vs last 20-week efficiency windows"],
                "strength": "high",
            },
            {
                "title": "Spend buys signups within every channel",
                "detail": "Weekly spend-signup correlation 0.44-0.84 (content 0.84, search 0.66) — efficiency, not spend, is the differentiator.",
                "evidence": ["per-channel weekly correlations"],
                "strength": "medium",
            },
        ),
        predictions=(
            {
                "claim": "Shifting $100/week from social to email adds ~90 signups/week.",
                "confidence": 0.8,
                "basis": "Observed efficiencies: email 1.011 vs social 0.034 signups/$.",
            },
        ),
        recommendations=(
            {
                "title": "Reallocate social to email/search",
                "action": "Move most social spend to the efficient engines.",
                "expected_impact": "~30x better return per dollar",
                "effort": "S",
                "priority": 1,
            },
            {
                "title": "Keep funding content",
                "action": "Sustain content investment; it compounds and passed referral.",
                "expected_impact": "Fastest-improving channel",
                "effort": "S",
                "priority": 2,
            },
            {
                "title": "Cap social at a brand floor",
                "action": "Hold social at its current minimum until tracking improves.",
                "expected_impact": "Stem the weakest dollar",
                "effort": "S",
                "priority": 3,
            },
        ),
    )


_STORY_BUILDERS: dict[str, Callable[[], Story]] = {
    "saas_churn": _saas_churn_story,
    "ecommerce_sales": _ecommerce_sales_story,
    "support_tickets": _support_tickets_story,
    "marketing_spend": _marketing_spend_story,
}

_STORY_CACHE: dict[str, Story] = {}


def load_story(key: str) -> Story:
    """Return the immutable scripted story for a sample-dataset key."""
    if key not in _STORY_BUILDERS:
        raise KeyError(f"unknown story key {key!r}; expected one of {sorted(_STORY_BUILDERS)}")
    if key not in _STORY_CACHE:
        _STORY_CACHE[key] = _STORY_BUILDERS[key]()
    return _STORY_CACHE[key]


# ── Plan resolution ──────────────────────────────────────────────────────


def _plan_from_template_dict(template: Optional[Mapping[str, Any]]) -> Optional[list[dict[str, Any]]]:
    """Use a template's expected_dag when it is well-formed and role-pinned."""
    if not template:
        return None
    dag = template.get("expected_dag")
    if not isinstance(dag, list) or not dag:
        return None
    plan: list[dict[str, Any]] = []
    for raw in dag:
        if not isinstance(raw, Mapping):
            return None
        node_id, agent = raw.get("id"), raw.get("agent")
        title = raw.get("title")
        if not isinstance(node_id, str) or not node_id:
            return None
        if not isinstance(title, str) or not title:
            return None
        if agent not in AGENT_ROLES:
            return None
        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
            return None
        plan.append(
            {
                "id": node_id,
                "title": title,
                "agent": agent,
                "depends_on": list(depends_on),
                "status": "pending",
            }
        )
    known_ids = {node["id"] for node in plan}
    for node in plan:
        if any(dep not in known_ids for dep in node["depends_on"]):
            return None
    return plan


# ── The player ───────────────────────────────────────────────────────────


class SimulatedRunPlayer:
    """Plays one full simulated AgentForge run as pinned envelope events.

    Construct with the runner-compatible kwargs (all optional except the
    mission) and :meth:`play` it::

        player = SimulatedRunPlayer(
            mission="Analyze why our churn spiked in Q3",
            run_id=run.id,
            template=template_dict,          # from /api/templates/{id}
            template_id=template_id,
            dataset_info=dataset_info,       # optional uploaded-dataset facts
            on_event=emitter.sync_sink(),    # runner wiring
        )
        events = await player.play()

    Every event is validated against the pinned envelope before being handed
    to ``on_event``; all emitted events are also returned as a list.
    """

    def __init__(
        self,
        mission: Optional[str] = None,
        *,
        run_id: Optional[str] = None,
        mission_text: Optional[str] = None,
        goal: Optional[str] = None,
        template: Optional[Mapping[str, Any]] = None,
        template_id: Optional[str] = None,
        dataset_path: Optional[str] = None,
        dataset_columns: Optional[Sequence[str]] = None,
        dataset_info: Optional[Mapping[str, Any]] = None,
        on_event: Optional[OnEvent] = None,
        speed: float = 1.0,
        seed: Optional[int] = None,
    ) -> None:
        resolved_mission = (mission or mission_text or goal or "").strip()
        if not resolved_mission:
            raise ValueError(
                "SimulatedRunPlayer requires a mission (mission=/mission_text=/goal=)"
            )
        self.mission: str = resolved_mission
        self.run_id: str = run_id or f"sim-{uuid.uuid4().hex[:12]}"
        self.template: Mapping[str, Any] = template or {}
        self.template_id: str = (
            template_id
            or (str(template.get("id")) if template and template.get("id") else "")
            or auto_select_template(self.mission)
        )
        if self.template_id not in TEMPLATE_IDS:
            # Unknown template id: keep it for labeling but plan canonically
            # from the closest pinned template so the DAG is always realistic.
            self._plan_template_id = auto_select_template(self.mission)
        else:
            self._plan_template_id = self.template_id
        self.dataset_path: Optional[str] = dataset_path
        self.dataset_columns: list[str] = [str(c) for c in (dataset_columns or [])]
        self.dataset_info: Mapping[str, Any] = dataset_info or {}
        self.on_event: Optional[OnEvent] = on_event
        self.speed: float = speed if isinstance(speed, (int, float)) else 1.0
        story_key = resolve_story_key(self.template_id, self.mission)
        self.story: Story = load_story(story_key)
        self.plan: list[dict[str, Any]] = (
            _plan_from_template_dict(self.template)
            or [dict(node) for node in CANONICAL_PLANS[self._plan_template_id]]
        )
        self._rng = random.Random(
            seed
            if seed is not None
            else zlib.crc32(
                f"{self.template_id}|{self.mission}".encode("utf-8")
            ) or SIMULATION_SEED
        )
        self._meter = TokenMeter()
        self._seq = 0
        self.emitted: list[dict[str, Any]] = []

    # ── event plumbing ───────────────────────────────────────────────────

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _emit(
        self,
        event_type: str,
        agent: Optional[str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Build (and validate) one envelope, then deliver it to the sink."""
        event = make_event(
            event_type,
            self.run_id,
            self._next_seq(),
            agent=agent,
            payload=payload,
            ts=utc_now_iso(),
        )
        self.emitted.append(event)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001 - a bad sink must not kill the run
                # Re-raise only if it is the runner's sink failing hard? No:
                # the runner's sink only schedules tasks; swallow and log.
                import logging

                logging.getLogger("agentforge.realtime.simulate").exception(
                    "on_event sink raised for run %s", self.run_id
                )
        return event

    async def _pause(self, kind: str) -> None:
        """Deterministic paced sleep for one event of ``kind``."""
        base = BASE_DELAYS.get(kind, 0.4)
        speed = self.speed if self.speed and self.speed > 0 else SIM_SPEED_INSTANT
        jitter = self._rng.uniform(0.85, 1.15)
        delay = (base * jitter) / speed
        if delay >= MIN_SLEEP_SECONDS:
            await asyncio.sleep(delay)

    # ── content helpers ──────────────────────────────────────────────────

    def _script_for(self, agent: str, occurrence: int) -> SubtaskScript:
        """Script for the ``occurrence``-th subtask of ``agent`` (clamped)."""
        scripts = self.story.scripts.get(agent)
        if not scripts:  # unknown agent / richer DAG: minimal generic block
            return SubtaskScript(
                thought=(
                    f"Working the {self.story.mission_theme} angle of this mission "
                    f"(simulated {agent} pass)."
                ),
                tools=(
                    ToolStep(
                        "csv_analyzer" if agent == "analyst" else "plan_dag",
                        f"demo analysis step {occurrence + 1}",
                        "step completed",
                    ),
                ),
            )
        return scripts[min(occurrence, len(scripts) - 1)]

    def _dataset_note(self) -> str:
        """Honest description of the data grounding for this run."""
        if self.dataset_info:
            rows = self.dataset_info.get("row_count")
            columns = self.dataset_info.get("columns") or self.dataset_columns
            joined = ", ".join(str(c) for c in columns) if columns else "unknown columns"
            return f"attached dataset ({rows} rows; columns: {joined})"
        return f"bundled sample dataset {self.story.dataset} ({self.story.rows:,} rows)"

    def _report_markdown(self) -> str:
        """Full markdown body for the final report artifact."""
        story = self.story
        lines: list[str] = [
            f"# AgentForge demo report — {story.mission_theme}",
            "",
            f"**Mission:** {self.mission}",
            "",
            f"> Simulated demo run (no LLM). Numbers are the measured facts of the "
            f"bundled sample dataset `{story.dataset}` ({story.rows:,} rows).",
            "",
            "## Insights",
            "",
        ]
        for i, insight in enumerate(story.insights, start=1):
            evidence = "; ".join(insight.get("evidence", ()))
            lines.append(
                f"{i}. **{insight['title']}** ({insight.get('strength', 'medium')}) — "
                f"{insight['detail']} _Evidence: {evidence}_"
            )
        lines += ["", "## Predictions", ""]
        for prediction in story.predictions:
            lines.append(
                f"- {prediction['claim']} (confidence {prediction['confidence']:.2f}; "
                f"basis: {prediction['basis']})"
            )
        lines += ["", "## Recommendations", ""]
        for rec in sorted(story.recommendations, key=lambda r: r.get("priority", 99)):
            lines.append(
                f"{rec.get('priority', '?')}. **{rec['title']}** — {rec['action']} "
                f"_(impact: {rec.get('expected_impact', '')}; effort: {rec.get('effort', '?')})_"
            )
        lines += [
            "",
            "---",
            f"_Data grounding: {self._dataset_note()}._",
        ]
        return "\n".join(lines)

    def _artifact_payload(
        self,
        subtask_id: str,
        draft: ArtifactDraft,
        counter: int,
    ) -> dict[str, Any]:
        """Assemble one artifact_created payload with honest labels."""
        data = dict(draft.data) if draft.data else None
        if draft.kind == "report_markdown" and data is not None:
            data["markdown"] = self._report_markdown()
        payload: dict[str, Any] = {
            "subtask_id": subtask_id,
            "artifact_id": f"art_{self.story.key}_{counter}",
            "kind": draft.kind,
            "name": draft.name,
            "summary": draft.summary,
            "simulated": True,
        }
        if data is not None:
            payload["data"] = data
        if self.dataset_path:
            payload["path"] = self.dataset_path
        return payload

    def _token_update_payload(self, agent: str) -> dict[str, Any]:
        """Deterministic, plausible token counts + cost for one subtask."""
        ordinal = sum(1 for e in self.emitted if e["type"] == "token_update")
        input_tokens = 940 + 215 * ordinal + (len(agent) * 37) % 160
        output_tokens = 240 + 85 * ordinal + (len(agent) * 53) % 90
        tally = self._meter.record(agent, input_tokens=input_tokens, output_tokens=output_tokens)
        return {
            "agent": agent,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": tally["cost_usd"],
            "run_total_usd": self._meter.run_total_usd(),
            "simulated": True,
        }

    # ── the play loop ────────────────────────────────────────────────────

    async def play(self, on_event: Optional[OnEvent] = None) -> list[dict[str, Any]]:
        """Stream the whole simulated run; returns every emitted envelope."""
        if on_event is not None:
            self.on_event = on_event

        self._emit(
            "run_started",
            agent=None,
            payload={
                "mission": self.mission,
                "mode": "demo",
                "simulated": True,
                "template_id": self.template_id,
                "story": self.story.key,
                "dataset": self.story.dataset,
                "data_grounding": self._dataset_note(),
            },
        )
        await self._pause("run_started")

        self._emit("plan_created", agent="planner", payload={"subtasks": self.plan})
        await self._pause("plan_created")

        # Per-agent occurrence counters so a 2-subtask agent gets both scripts.
        occurrence: dict[str, int] = {role: 0 for role in AGENT_ROLES}
        artifact_counter = 0

        for index, subtask in enumerate(self.plan):
            agent = str(subtask["agent"])
            subtask_id = str(subtask["id"])
            title = str(subtask["title"])
            nth = occurrence.get(agent, 0)
            occurrence[agent] = nth + 1
            script = self._script_for(agent, nth)

            self._emit(
                "agent_started",
                agent=agent,
                payload={"subtask_id": subtask_id, "title": title},
            )
            await self._pause("agent_started")

            self._emit(
                "thought_summary",
                agent=agent,
                payload={"subtask_id": subtask_id, "summary": script.thought},
            )
            await self._pause("thought_summary")

            for tool_step in script.tools:
                self._emit(
                    "tool_call",
                    agent=agent,
                    payload={
                        "subtask_id": subtask_id,
                        "tool": tool_step.tool,
                        "args_summary": tool_step.args_summary,
                        "ok": True,
                    },
                )
                await self._pause("tool_call")
                self._emit(
                    "tool_result",
                    agent=agent,
                    payload={
                        "subtask_id": subtask_id,
                        "tool": tool_step.tool,
                        "args_summary": tool_step.result_summary,
                        "ok": True,
                    },
                )
                await self._pause("tool_result")

            for draft in script.artifacts:
                artifact_counter += 1
                self._emit(
                    "artifact_created",
                    agent=agent,
                    payload=self._artifact_payload(subtask_id, draft, artifact_counter),
                )
                await self._pause("artifact_created")

            self._emit(
                "step_completed",
                agent=agent,
                payload={"subtask_id": subtask_id},
            )
            await self._pause("step_completed")

            self._emit(
                "agent_finished",
                agent=agent,
                payload={"subtask_id": subtask_id},
            )
            await self._pause("agent_finished")

            self._emit(
                "token_update",
                agent=agent,
                payload=self._token_update_payload(agent),
            )
            await self._pause("token_update")

            if index < len(self.plan) - 1:
                await self._pause("inter_subtask")

        await self._pause("pre_finish")
        self._emit("run_finished", agent=None, payload={"report_ready": True})
        return list(self.emitted)


async def run_simulation(
    mission: str,
    template_id: Optional[str] = None,
    on_event: Optional[OnEvent] = None,
    speed: float = 1.0,
    run_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Play one full simulated run and return every pinned envelope emitted.

    Args:
        mission: the business goal in plain language (required).
        template_id: one of the pinned template ids, or ``None`` to
            auto-select by mission keywords.
        on_event: optional sync callback receiving each envelope dict.
        speed: pacing multiplier (``1.0`` ≈ 25-45 s total; ``<=0`` instant).
        run_id: optional explicit run id (a ``sim-…`` id is generated otherwise).

    Returns:
        The ordered list of emitted envelope dicts (seq starts at 1 and the
        last event is ``run_finished`` with ``{"report_ready": True}``).
    """
    player = SimulatedRunPlayer(
        mission=mission,
        template_id=template_id,
        on_event=on_event,
        speed=speed,
        run_id=run_id,
    )
    return await player.play()


# Re-export for callers that want to validate simulator output.
_PINNED_EVENT_TYPES: tuple[str, ...] = EVENT_TYPES
