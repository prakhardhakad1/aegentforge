/**
 * Demo data — realistic mock content behind NEXT_PUBLIC_DEMO_MODE=1 (and the
 * automatic fallback when the API is unreachable). All shapes match the
 * canonical Report / Template / Mission / ChartSpec models in INTERFACES.md.
 *
 * Honesty note: this is *simulated* demo content, clearly labelled in the UI.
 */
import {
  type AgentForgeEvent,
  type ChartSpec,
  type Dataset,
  type Mission,
  type Report,
  type Template,
  type TokenUsage,
} from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Templates (ids pinned in INTERFACES.md)                             */
/* ------------------------------------------------------------------ */

export const DEMO_TEMPLATES: Template[] = [
  {
    id: "market_research_team",
    name: "Market Research Team",
    description:
      "Sizes markets, maps competitors and surfaces demand signals. Best for go/no-go questions: new markets, new segments, pricing research, competitive scans.",
    tags: ["market sizing", "competitors", "demand signals", "TAM"],
    team: [
      {
        role: "planner",
        title: "Research Lead",
        system_prompt:
          "You are a research lead. Break the goal into a minimal DAG of subtasks for researcher/analyst/forecaster/critic. Prefer 3-6 concrete subtasks with clear outputs.",
      },
      {
        role: "researcher",
        title: "Market Scout",
        system_prompt:
          "You are a market researcher. Search the web for market size, growth rates, competitor moves and demand signals. Cite every claim.",
      },
      {
        role: "analyst",
        title: "Data Analyst",
        system_prompt:
          "You are a data analyst. Run statistics on uploaded datasets, build comparison tables and charts, and quantify segment differences.",
      },
      {
        role: "forecaster",
        title: "Forecaster",
        system_prompt:
          "You are a forecaster. Produce simple, defensible projections (CAGR, scenario ranges) from the gathered evidence. Always state confidence and basis.",
      },
      {
        role: "critic",
        title: "Skeptical Reviewer",
        system_prompt:
          "You are a critic. Flag weak claims, stale data, unstated assumptions and overconfident predictions. Rank evidence by strength.",
      },
    ],
    planner_prompt:
      "Plan a market research mission for the goal below. Output a DAG of subtasks assigned to researcher, analyst, forecaster and critic.",
    sample_mission:
      "Should we expand into the DACH market this year? Size it, name the top 3 risks, and recommend a go/no-go.",
    expected_dag: [
      { id: "s1", title: "Scope the research question", agent: "planner", depends_on: [] },
      { id: "s2", title: "Gather market & competitor evidence", agent: "researcher", depends_on: ["s1"] },
      { id: "s3", title: "Analyze survey / internal data", agent: "analyst", depends_on: ["s1"] },
      { id: "s4", title: "Forecast 3-year scenario", agent: "forecaster", depends_on: ["s2", "s3"] },
      { id: "s5", title: "Review claims & rank evidence", agent: "critic", depends_on: ["s4"] },
    ],
    report_outline: [
      "Executive summary",
      "Market size & growth",
      "Competitive landscape",
      "Demand signals",
      "Forecast scenarios",
      "Ranked recommendations",
    ],
  },
  {
    id: "sales_insights_team",
    name: "Sales Insights Team",
    description:
      "Digs into pipelines, churn and revenue data. Best for 'why did our numbers move?' questions: churn spikes, win-rate drops, cohort shifts, pricing effects.",
    tags: ["churn", "pipeline", "cohorts", "revenue"],
    team: [
      {
        role: "planner",
        title: "Revenue Lead",
        system_prompt:
          "You are a revenue operations lead. Decompose the goal into a DAG of analysis subtasks for researcher/analyst/forecaster/critic with measurable outputs.",
      },
      {
        role: "researcher",
        title: "Context Researcher",
        system_prompt:
          "You are a researcher. Find external context: industry benchmarks, seasonality, competitor pricing moves that could explain the metric change.",
      },
      {
        role: "analyst",
        title: "Data Analyst",
        system_prompt:
          "You are a data analyst. Run Python on the uploaded CSV: segment stats, trend deltas, cohort comparisons, charts. State every caveat.",
      },
      {
        role: "forecaster",
        title: "Forecaster",
        system_prompt:
          "You are a forecaster. Project the metric forward under status-quo and intervention scenarios. State confidence and basis for each.",
      },
      {
        role: "critic",
        title: "Skeptical Reviewer",
        system_prompt:
          "You are a critic. Attack the causal claims: confounders, sample bias, small cohorts. Rank insights by evidence strength before the report ships.",
      },
    ],
    planner_prompt:
      "Plan a sales/revenue analysis mission for the goal below. Output a DAG of subtasks assigned to researcher, analyst, forecaster and critic.",
    sample_mission:
      "Analyze why our churn spiked in Q3 and recommend 3 fixes with expected impact.",
    expected_dag: [
      { id: "s1", title: "Frame the churn question", agent: "planner", depends_on: [] },
      { id: "s2", title: "Benchmark against industry norms", agent: "researcher", depends_on: ["s1"] },
      { id: "s3", title: "Segment & trend the churn data", agent: "analyst", depends_on: ["s1"] },
      { id: "s4", title: "Project churn under 2 scenarios", agent: "forecaster", depends_on: ["s3"] },
      { id: "s5", title: "Attack the claims, rank fixes", agent: "critic", depends_on: ["s2", "s4"] },
    ],
    report_outline: [
      "Executive summary",
      "What moved, and when",
      "Segment breakdown",
      "Root-cause candidates",
      "Churn forecast",
      "Ranked recommendations",
    ],
  },
  {
    id: "support_triage_team",
    name: "Support Triage Team",
    description:
      "Clusters ticket volume into themes, finds the biggest pain points, and ranks what to automate first. Best for support backlogs, ticket taxonomies, deflection planning.",
    tags: ["tickets", "automation", "deflection", "themes"],
    team: [
      {
        role: "planner",
        title: "Triage Lead",
        system_prompt:
          "You are a support operations lead. Break the goal into a DAG of subtasks for researcher/analyst/forecaster/critic aimed at a triage report.",
      },
      {
        role: "researcher",
        title: "Docs Researcher",
        system_prompt:
          "You are a researcher. Check whether recurring issues map to known bugs, doc gaps or feature requests; note upstream fixes that ship soon.",
      },
      {
        role: "analyst",
        title: "Data Analyst",
        system_prompt:
          "You are a data analyst. Cluster the ticket export by theme, compute volume/effort per theme, and chart the distribution.",
      },
      {
        role: "forecaster",
        title: "Forecaster",
        system_prompt:
          "You are a forecaster. Estimate ticket volume under 'do nothing' vs 'automate top themes' scenarios for next quarter.",
      },
      {
        role: "critic",
        title: "Skeptical Reviewer",
        system_prompt:
          "You are a critic. Challenge theme boundaries, small-sample themes and optimistic deflection claims. Rank automation candidates by ROI.",
      },
    ],
    planner_prompt:
      "Plan a support triage mission for the goal below. Output a DAG of subtasks assigned to researcher, analyst, forecaster and critic.",
    sample_mission:
      "Triage last month's 1,240 support tickets: top 5 themes and what to automate first.",
    expected_dag: [
      { id: "s1", title: "Define triage rubric", agent: "planner", depends_on: [] },
      { id: "s2", title: "Map themes to known issues", agent: "researcher", depends_on: ["s1"] },
      { id: "s3", title: "Cluster & count ticket themes", agent: "analyst", depends_on: ["s1"] },
      { id: "s4", title: "Forecast deflection impact", agent: "forecaster", depends_on: ["s2", "s3"] },
      { id: "s5", title: "Rank automation candidates", agent: "critic", depends_on: ["s4"] },
    ],
    report_outline: [
      "Executive summary",
      "Theme distribution",
      "Effort & volume leaders",
      "Deflection forecast",
      "Automation backlog",
    ],
  },
];

/* ------------------------------------------------------------------ */
/* Missions                                                            */
/* ------------------------------------------------------------------ */

export const DEMO_MISSIONS: Mission[] = [
  {
    id: "demo-mission-1",
    goal: "Analyze why our churn spiked in Q3 and recommend 3 fixes with expected impact.",
    template_id: "sales_insights_team",
    dataset_id: "demo-dataset-1",
    created_at: "2026-10-04T09:12:00Z",
  },
  {
    id: "demo-mission-2",
    goal: "Should we expand into the DACH market this year? Size it, name the top 3 risks, and recommend a go/no-go.",
    template_id: "market_research_team",
    dataset_id: null,
    created_at: "2026-10-04T11:40:00Z",
  },
  {
    id: "demo-mission-3",
    goal: "Triage last month's 1,240 support tickets: top 5 themes and what to automate first.",
    template_id: "support_triage_team",
    dataset_id: "demo-dataset-2",
    created_at: "2026-10-04T14:05:00Z",
  },
];

/* ------------------------------------------------------------------ */
/* Datasets                                                            */
/* ------------------------------------------------------------------ */

export const DEMO_DATASETS: Record<string, Dataset> = {
  "demo-dataset-1": {
    id: "demo-dataset-1",
    filename: "q3_subscribers.csv",
    row_count: 1840,
    columns: ["customer_id", "plan", "monthly_spend", "logins_per_week", "tickets_opened", "churned"],
    dtypes: {
      customer_id: "object",
      plan: "object",
      monthly_spend: "float64",
      logins_per_week: "int64",
      tickets_opened: "int64",
      churned: "int64",
    },
    preview: [
      ["CU-1001", "starter", 29, 1, 3, 1],
      ["CU-1002", "pro", 99, 11, 0, 0],
      ["CU-1003", "starter", 29, 0, 5, 1],
      ["CU-1004", "business", 299, 14, 1, 0],
      ["CU-1005", "pro", 99, 2, 4, 1],
    ],
    quality_notes: [
      "6 rows missing logins_per_week (0.3%) — dropped from per-login stats.",
      "'churned' is 0/1; overall churn rate 9.4% (vs 5.1% in Q2).",
    ],
  },
  "demo-dataset-2": {
    id: "demo-dataset-2",
    filename: "support_tickets.csv",
    row_count: 1240,
    columns: ["ticket_id", "created_at", "theme", "first_response_hours", "resolved", "csat"],
    dtypes: {
      ticket_id: "object",
      created_at: "datetime64[ns]",
      theme: "object",
      first_response_hours: "float64",
      resolved: "int64",
      csat: "float64",
    },
    preview: [
      ["TK-5501", "2026-09-02T08:14:00Z", "billing", 7.2, 1, 3],
      ["TK-5502", "2026-09-02T09:03:00Z", "sso_login", 31.5, 1, 2],
      ["TK-5503", "2026-09-02T09:47:00Z", "export_csv", 4.8, 1, 4],
      ["TK-5504", "2026-09-02T11:20:00Z", "sso_login", 44.1, 0, null],
      ["TK-5505", "2026-09-03T07:55:00Z", "billing", 6.9, 1, 3],
    ],
    quality_notes: [
      "csat missing on unresolved tickets (expected).",
      "theme was auto-assigned in-product; 4% fall into 'other'.",
    ],
  },
};

/** Sample-dataset chips offered on /new (prefill goal + dataset). */
export const SAMPLE_DATASETS: Array<{
  id: string;
  label: string;
  description: string;
  goal: string;
  templateId: string;
  datasetId: string | null;
}> = [
  {
    id: "saas_churn",
    label: "SaaS churn (1,840 rows)",
    description: "Subscribers with plan, spend, usage, tickets, churn flag.",
    goal: "Analyze why our churn spiked in Q3 and recommend 3 fixes with expected impact.",
    templateId: "sales_insights_team",
    datasetId: "demo-dataset-1",
  },
  {
    id: "support_tickets",
    label: "Support tickets (1,240 rows)",
    description: "One month of tickets with theme, response time, CSAT.",
    goal: "Triage last month's 1,240 support tickets: top 5 themes and what to automate first.",
    templateId: "support_triage_team",
    datasetId: "demo-dataset-2",
  },
  {
    id: "pipeline",
    label: "Sales pipeline (2,120 rows)",
    description: "Deals with stage, value, source, close date.",
    goal: "Which pipeline stage leaks the most revenue this quarter, and what should we fix first?",
    templateId: "sales_insights_team",
    datasetId: "demo-dataset-1",
  },
  {
    id: "market_survey",
    label: "Market survey (860 rows)",
    description: "Survey responses with segment, willingness-to-pay, region.",
    goal: "Should we expand into the DACH market this year? Size it and name the top 3 risks.",
    templateId: "market_research_team",
    datasetId: null,
  },
];

/* ------------------------------------------------------------------ */
/* Charts                                                              */
/* ------------------------------------------------------------------ */

function chart(spec: Omit<ChartSpec, "id"> & { id: string }): ChartSpec {
  return spec;
}

export const CHURN_CHARTS: ChartSpec[] = [
  chart({
    id: "chart_churn_by_month",
    kind: "line",
    title: "Monthly churn rate, Q1–Q4",
    x_label: "Month",
    y_label: "Churn rate (%)",
    data: [
      { label: "Apr", x: 4, y: 5.0 },
      { label: "May", x: 5, y: 5.2 },
      { label: "Jun", x: 6, y: 5.1 },
      { label: "Jul", x: 7, y: 6.8 },
      { label: "Aug", x: 8, y: 8.9 },
      { label: "Sep", x: 9, y: 12.4 },
      { label: "Oct", x: 10, y: 10.1 },
    ],
    notes: "Churn accelerates Aug→Sep, peaking at 12.4% in September (2.4x the June baseline).",
  }),
  chart({
    id: "chart_churn_by_plan",
    kind: "bar",
    title: "Q3 churn rate by plan",
    x_label: "Plan",
    y_label: "Churn rate (%)",
    data: [
      { label: "Starter", x: 0, y: 15.8 },
      { label: "Pro", x: 1, y: 7.9 },
      { label: "Business", x: 2, y: 3.2 },
    ],
    notes: "Starter accounts for 71% of churned logos despite being 34% of the base.",
  }),
  chart({
    id: "chart_churn_by_logins",
    kind: "pie",
    title: "Churned customers by weekly-logins bucket",
    x_label: "Logins bucket",
    y_label: "Share of churned",
    data: [
      { label: "0–1 logins/wk", x: 0, y: 58 },
      { label: "2–5 logins/wk", x: 1, y: 27 },
      { label: "6–10 logins/wk", x: 2, y: 10 },
      { label: "10+ logins/wk", x: 3, y: 5 },
    ],
    notes: "58% of churned customers logged in less than once a week before cancelling.",
  }),
];

export const MARKET_CHARTS: ChartSpec[] = [
  chart({
    id: "chart_dach_tam",
    kind: "bar",
    title: "Serviceable market by country (€M ARR)",
    x_label: "Country",
    y_label: "€M ARR",
    data: [
      { label: "Germany", x: 0, y: 410 },
      { label: "Austria", x: 1, y: 48 },
      { label: "Switzerland", x: 2, y: 62 },
    ],
    notes: "Germany is ~79% of the DACH serviceable market for our price band.",
  }),
  chart({
    id: "chart_growth",
    kind: "line",
    title: "Category growth, 2022–2026E",
    x_label: "Year",
    y_label: "Market size (€M)",
    data: [
      { label: "2022", x: 2022, y: 310 },
      { label: "2023", x: 2023, y: 355 },
      { label: "2024", x: 2024, y: 402 },
      { label: "2025", x: 2025, y: 448 },
      { label: "2026E", x: 2026, y: 498 },
    ],
    notes: "~12.6% CAGR — steady, not explosive; timing is not a forced mover.",
  }),
];

export const SUPPORT_CHARTS: ChartSpec[] = [
  chart({
    id: "chart_themes",
    kind: "bar",
    title: "Ticket volume by theme (September)",
    x_label: "Theme",
    y_label: "Tickets",
    data: [
      { label: "Billing", x: 0, y: 372 },
      { label: "SSO login", x: 1, y: 296 },
      { label: "CSV export", x: 2, y: 204 },
      { label: "API limits", x: 3, y: 156 },
      { label: "Onboarding", x: 4, y: 121 },
      { label: "Other", x: 5, y: 91 },
    ],
    notes: "Top 3 themes are 70% of volume.",
  }),
  chart({
    id: "chart_csat",
    kind: "scatter",
    title: "CSAT vs first-response time",
    x_label: "First response (hours)",
    y_label: "CSAT (1–5)",
    data: [
      { label: "Billing", x: 7.1, y: 3.2 },
      { label: "SSO login", x: 38.4, y: 2.1 },
      { label: "CSV export", x: 5.2, y: 4.1 },
      { label: "API limits", x: 12.8, y: 3.0 },
      { label: "Onboarding", x: 9.6, y: 3.4 },
      { label: "Other", x: 11.2, y: 3.1 },
    ],
    notes: "Every extra 10h of first-response delay costs ~0.5 CSAT points.",
  }),
];

/* ------------------------------------------------------------------ */
/* Reports                                                             */
/* ------------------------------------------------------------------ */

export const DEMO_REPORTS: Record<string, Report> = {
  "demo-run-1": {
    title: "Q3 Churn Spike — Root Causes & Ranked Fixes",
    mission: "Analyze why our churn spiked in Q3 and recommend 3 fixes with expected impact.",
    style: "sales_insights",
    executive_summary:
      "Q3 churn rose from 5.1% to 9.4%, driven overwhelmingly by Starter-plan customers with low weekly usage (0–1 logins) and 3+ open support tickets. The spike is concentrated, not broad-based: Business-plan churn is flat. The single strongest predictor of churn is login activity in the 30 days before cancel; support-ticket count compounds it. Three fixes ranked by expected impact: an onboarding re-engagement flow for low-usage Starter accounts, a support SLA for Starter tickets, and a pre-cancel save offer. Modeled together, they project Q4 churn back to ~6.2% (medium confidence).",
    insights: [
      {
        title: "Churn is concentrated in low-usage Starter accounts",
        detail:
          "58% of churned customers logged in 0–1 times/week in their final month. Starter-plan churn hit 15.8% in Q3 vs 7.9% for Pro and 3.2% for Business.",
        evidence: [
          "q3_subscribers.csv: churn rate by plan (Starter 15.8%, n=626; Pro 7.9%, n=812; Business 3.2%, n=402)",
          "Churned customers by logins bucket: 58% at 0–1 logins/week",
          "Login activity drops a median 62% in the 30 days before cancel",
        ],
        strength: "high",
      },
      {
        title: "The spike is a September event, not a Q3 trend",
        detail:
          "Monthly churn was stable through July (6.8%), then jumped to 8.9% in August and 12.4% in September. A single-quarter average hides a step change.",
        evidence: [
          "Monthly churn series Apr–Oct: 5.0 → 5.2 → 5.1 → 6.8 → 8.9 → 12.4 → 10.1",
          "October partial data shows recovery to 10.1%, suggesting the driver is transient",
        ],
        strength: "high",
      },
      {
        title: "Open support tickets compound churn risk",
        detail:
          "Churned Starter customers opened a median of 3 tickets in their final month vs 1 for retained customers. Customers with 4+ open tickets churned at 21%, 5.6x the base rate.",
        evidence: [
          "tickets_opened vs churned: 0–1 tickets → 4.1% churn; 2–3 → 8.8%; 4+ → 21.3%",
          "Median first-response time for Starter tickets rose from 6h (Q2) to 19h (Q3)",
        ],
        strength: "medium",
      },
      {
        title: "Price-sensitive segment grew before the spike",
        detail:
          "Starter signups grew 41% QoQ while Pro growth stayed flat — the churn spike partially reflects a mix shift toward a price-sensitive, low-engagement cohort, not deteriorating product quality.",
        evidence: [
          "New Starter signups: Q2 489 → Q3 689 (+41%)",
          "Pro plan churn rate moved only 7.2% → 7.9% QoQ",
        ],
        strength: "medium",
      },
    ],
    charts: CHURN_CHARTS,
    predictions: [
      {
        claim:
          "If no action is taken, Q4 churn lands between 8.5% and 9.8% as the September cohort exhausts its cycle.",
        confidence: 0.72,
        basis:
          "Trend extrapolation on the monthly series + cohort exposure: October already prints 10.1% and the low-usage Starter mix keeps growing.",
      },
      {
        claim:
          "The 3 recommended fixes combined bring Q4 churn back to ~6.2% (range 5.8–7.1%).",
        confidence: 0.58,
        basis:
          "Modeled per-fix lift on the segments they target (re-engagement flow on 0–1 logins bucket, SLA on 4+ ticket segment, save offer at cancel intent), each discounted by 30% for execution risk.",
      },
      {
        claim: "Starter churn normalizes below 9% by December even without intervention.",
        confidence: 0.64,
        basis:
          "The step change tracks the Q3 signup surge aging through its first 90 days; October data already shows partial mean reversion.",
      },
    ],
    recommendations: [
      {
        title: "Launch a low-usage re-engagement flow for Starter accounts",
        action:
          "Trigger an in-app + email sequence when a Starter account falls below 1 login/week for 14 days; route non-responders to a check-in call.",
        expected_impact:
          "Addresses 58% of churn volume; modeled to cut Starter churn 15.8% → ~11% in one quarter.",
        effort: "M",
        priority: 1,
      },
      {
        title: "Stand up a Starter-tier support SLA",
        action:
          "Cap first response at 8 business hours for Starter tickets and auto-escalate any ticket open >48h.",
        expected_impact:
          "Removes the strongest compounding factor (4+ open tickets → 21.3% churn); expected ~1.1pt churn reduction.",
        effort: "S",
        priority: 2,
      },
      {
        title: "Offer a pre-cancel save on the cancel page",
        action:
          "At cancel, show a 2-month 50% discount or a free plan downgrade (keep data) instead of a hard cancel.",
        expected_impact:
          "Industry save rates 10–18% on pre-cancel offers; modeled 0.6–0.9pt churn reduction.",
        effort: "S",
        priority: 3,
      },
    ],
    appendix:
      "Method: pandas on q3_subscribers.csv (1,840 rows, 6 dropped for missing logins_per_week). Churn defined as churned=1 within the quarter. Forecast: trend + cohort exposure model with scenario overrides; confidence is analyst judgment, not a statistical interval. All figures are demo-mode simulated data.",
  },
  "demo-run-2": {
    title: "DACH Market Expansion — Sizing, Risks & Go/No-Go",
    mission:
      "Should we expand into the DACH market this year? Size it, name the top 3 risks, and recommend a go/no-go.",
    style: "market_research",
    executive_summary:
      "The DACH serviceable market for our price band is ~€520M ARR growing at ~12.6% CAGR, with Germany at 79% of it. Competition is real but fragmented: no incumbent holds >15% share in our segment. The economics work, but not fast — a realistic year-1 outcome is €0.9–1.6M ARR, meaning expansion is a 2027-impact bet made in 2026. Recommendation: conditional GO — enter Germany via a local reseller/partner motion this year (low burn), and defer direct sales hiring until €1M local ARR or a lighthouse customer anchors the move. Top risks: GDPR/data-residency requirements, competitor price aggression, and slow German procurement cycles.",
    insights: [
      {
        title: "Germany alone justifies a beachhead — Austria/Switzerland do not",
        detail:
          "The German serviceable market is ~€410M vs €48M (AT) and €62M (CH). A single-country entry captures ~79% of reachable demand at ~40% of the multi-country cost.",
        evidence: [
          "Serviceable market by country: DE €410M, CH €62M, AT €48M",
          "Our segment (teams 10–200 seats) is 34% of DE category spend",
        ],
        strength: "high",
      },
      {
        title: "No incumbent dominates our segment",
        detail:
          "The top 3 competitors each hold 8–15% of the segment; 55% of the market is fragmented across local tools with weak analytics — a wedge exists.",
        evidence: [
          "Competitor share scan: A 15%, B 11%, C 8%, fragmented long tail 55%+",
          "Local-tool reviews cluster complaints on reporting/export gaps (the gaps our product leads on)",
        ],
        strength: "medium",
      },
      {
        title: "Category growth is steady, not explosive — timing is optional",
        detail:
          "~12.6% CAGR means waiting a year costs little in share terms; the market will not be 'gone'. This argues for the low-burn partner motion over a full direct investment now.",
        evidence: [
          "Category size 2022–2026E: €310M → €498M (~12.6% CAGR)",
          "No step-change events (regulatory, M&A) found that would reward being early",
        ],
        strength: "medium",
      },
      {
        title: "Data residency is the #1 stated buying requirement",
        detail:
          "In survey responses, EU data hosting appears as a hard requirement for 68% of DACH respondents — a checkbox gate before product evaluation even starts.",
        evidence: [
          "market_survey: 68% of respondents mark 'EU-only data hosting' as required",
          "Two competitor launches in 2025 led with 'data residency' messaging",
        ],
        strength: "high",
      },
    ],
    charts: MARKET_CHARTS,
    predictions: [
      {
        claim: "Year-1 DACH ARR lands between €0.9M and €1.6M via the partner motion.",
        confidence: 0.55,
        basis:
          "Bottom-up: 3 resellers × mid pipeline conversion benchmarks × our average contract value, cross-checked against comparable company year-1 entries (2 public post-mortems).",
      },
      {
        claim: "Without EU data residency, win rate in DACH stays under 10% regardless of spend.",
        confidence: 0.78,
        basis:
          "68% of respondents gate on it as a hard requirement; the two competitor launches made it table stakes.",
      },
      {
        claim: "Germany procurement cycles delay signed deals by 3–5 months vs our US baseline.",
        confidence: 0.6,
        basis:
          "Benchmarked procurement-length reports plus reseller interviews referenced in the research notes.",
      },
    ],
    recommendations: [
      {
        title: "Enter Germany only, via 2–3 local resellers",
        action:
          "Sign reseller/MSP partners covering DACH by March; localize the site and billing to EUR; skip direct sales hires until €1M local ARR.",
        expected_impact:
          "Captures ~79% of the reachable market at low burn; year-1 upside €0.9–1.6M ARR without fixed sales cost.",
        effort: "M",
        priority: 1,
      },
      {
        title: "Ship EU data residency before any DACH push",
        action:
          "Add an EU hosting region and a data-processing agreement template; make it a headline item on the pricing page.",
        expected_impact:
          "Removes the gate for 68% of buyers; without it, win rate is predicted <10% and ad spend is wasted.",
        effort: "L",
        priority: 2,
      },
      {
        title: "Land one lighthouse German customer before scaling spend",
        action:
          "Offer a design-partner deal to a mid-market German team (discounted year-1) in exchange for a public case study.",
        expected_impact:
          "Reference effect shortens the 3–5 month procurement drag for every later deal.",
        effort: "S",
        priority: 3,
      },
    ],
    appendix:
      "Sources: web research notes (market reports, competitor pages, review sites) summarized by the researcher agent; survey dataset aggregated by the analyst agent; scenario model by the forecaster. All figures are demo-mode simulated data.",
  },
  "demo-run-3": {
    title: "September Support Triage — Themes & Automation Backlog",
    mission: "Triage last month's 1,240 support tickets: top 5 themes and what to automate first.",
    style: "support_triage",
    executive_summary:
      "September's 1,240 tickets cluster into 6 themes; the top 3 (Billing 372, SSO login 296, CSV export 204) are 70% of volume. SSO login is the outlier on pain: 38h median first response, 2.1 CSAT, and 24% of tickets unresolved — driven by a known session-expiry bug plus missing SAML docs. Highest-ROI automation: billing self-service (invoice fetch + plan changes), which deflects an estimated 55% of billing volume, then SSO self-service diagnostics. Doing both projects October volume down ~30% at modest effort. CSV export should be fixed at the product level, not deflected — it is a feature gap, not a support problem.",
    insights: [
      {
        title: "SSO login is the pain outlier, not the biggest theme",
        detail:
          "Billing is bigger (372 tickets) but SSO login has 38.4h median first response, 2.1 CSAT and 24% unresolved — the worst customer experience by far.",
        evidence: [
          "Theme table: SSO 296 tickets, 24% unresolved, CSAT 2.1",
          "First-response time by theme: SSO 38.4h vs 7.1h billing",
        ],
        strength: "high",
      },
      {
        title: "Top 3 themes are 70% of volume — triage is highly concentrated",
        detail:
          "Billing (372) + SSO (296) + CSV export (204) = 872 of 1,240 tickets. Automating or fixing three flows touches most of the queue.",
        evidence: [
          "Volume by theme: 372/296/204/156/121/91 across 6 themes",
          "Agent categorization time on top-3 themes: 61% of logged hours",
        ],
        strength: "high",
      },
      {
        title: "SSO pain traces to one known bug plus a docs gap",
        detail:
          "Researcher mapping: 61% of SSO tickets match a known session-expiry bug (fix shipping v2.9) and 27% are SAML configuration questions answered nowhere in the docs.",
        evidence: [
          "61% of SSO tickets quote the same error signature (session-expiry, ERR-2041)",
          "27% are 'how do I configure SAML' questions; no doc page exists",
        ],
        strength: "medium",
      },
      {
        title: "CSV export is a product gap, not a deflection candidate",
        detail:
          "CSV export tickets have the best support metrics (5.2h response, 4.1 CSAT) but repeat monthly — customers want the export fixed, not handled faster.",
        evidence: [
          "CSAT vs response scatter: export theme at 5.2h / 4.1 CSAT",
          "Export requests recur every month at ~200 volume with no trend",
        ],
        strength: "medium",
      },
    ],
    charts: SUPPORT_CHARTS,
    predictions: [
      {
        claim: "Automating billing + SSO self-service cuts October volume ~30% (±6pts).",
        confidence: 0.63,
        basis:
          "Deflection benchmarks on comparable self-service flows (45–65% on billing) applied to the theme mix; SSO deflection held conservative at 35% pending the v2.9 fix.",
      },
      {
        claim: "The v2.9 session-expiry fix removes ~180 tickets/month within 6 weeks of release.",
        confidence: 0.7,
        basis:
          "61% of SSO tickets match the bug signature; historical post-fix ticket decay from two prior bug fixes averaged 80% resolution within 6 weeks.",
      },
      {
        claim: "Without action, November volume grows to ~1,450 tickets (+17%) on trend.",
        confidence: 0.55,
        basis:
          "3-month linear trend plus the onboarding-theme growth rate (new-customer cohort growth).",
      },
    ],
    recommendations: [
      {
        title: "Build billing self-service (invoices + plan changes)",
        action:
          "Ship an in-app billing page covering invoice download, plan upgrade/downgrade and payment-method update; route chat only for failures.",
        expected_impact:
          "Deflects ~55% of the 372 billing tickets/month (~205 tickets, the single biggest win).",
        effort: "M",
        priority: 1,
      },
      {
        title: "Add SSO self-diagnostics + a SAML setup guide",
        action:
          "Publish a step-by-step SAML configuration guide and an in-app 'test my SSO' checker; prioritize the v2.9 session-expiry fix.",
        expected_impact:
          "~35% deflection on 296 tickets now, rising toward 60% after v2.9 lands.",
        effort: "S",
        priority: 2,
      },
      {
        title: "Fix CSV export in-product instead of deflecting",
        action:
          "Add the two most-requested export fields and async large-file export; announce in the release notes.",
        expected_impact:
          "Removes ~200 recurring tickets/month at the source; support-side automation would only hide the gap.",
        effort: "M",
        priority: 3,
      },
    ],
    appendix:
      "Method: pandas clustering on support_tickets.csv (1,240 rows, theme from in-product auto-tag, 4% 'other'); response-time and CSAT stats per theme; deflection model from published benchmarks discounted 20%. All figures are demo-mode simulated data.",
  },
};

/* ------------------------------------------------------------------ */
/* Token usage snapshots (per seeded run)                              */
/* ------------------------------------------------------------------ */

export const DEMO_TOKEN_USAGE: Record<string, TokenUsage> = {
  "demo-run-1": {
    per_agent: {
      planner: { input_tokens: 2140, output_tokens: 1180, cost_usd: 0.0106 },
      researcher: { input_tokens: 8900, output_tokens: 3210, cost_usd: 0.0402 },
      analyst: { input_tokens: 12400, output_tokens: 2680, cost_usd: 0.0483 },
      forecaster: { input_tokens: 7300, output_tokens: 1490, cost_usd: 0.0277 },
      critic: { input_tokens: 9600, output_tokens: 1720, cost_usd: 0.0368 },
    },
    totals: { input_tokens: 40340, output_tokens: 10280, cost_usd: 0.1636 },
  },
  "demo-run-2": {
    per_agent: {
      planner: { input_tokens: 1980, output_tokens: 1050, cost_usd: 0.0097 },
      researcher: { input_tokens: 11200, output_tokens: 4380, cost_usd: 0.0507 },
      analyst: { input_tokens: 5100, output_tokens: 1420, cost_usd: 0.0213 },
      forecaster: { input_tokens: 6800, output_tokens: 1610, cost_usd: 0.0272 },
      critic: { input_tokens: 8900, output_tokens: 1510, cost_usd: 0.0342 },
    },
    totals: { input_tokens: 33980, output_tokens: 9970, cost_usd: 0.1431 },
  },
  "demo-run-3": {
    per_agent: {
      planner: { input_tokens: 1760, output_tokens: 940, cost_usd: 0.0087 },
      researcher: { input_tokens: 6400, output_tokens: 2140, cost_usd: 0.0282 },
      analyst: { input_tokens: 9800, output_tokens: 2210, cost_usd: 0.0386 },
      forecaster: { input_tokens: 5900, output_tokens: 1180, cost_usd: 0.0231 },
      critic: { input_tokens: 7200, output_tokens: 1330, cost_usd: 0.0280 },
    },
    totals: { input_tokens: 31060, output_tokens: 7800, cost_usd: 0.1266 },
  },
};

/* ------------------------------------------------------------------ */
/* Mission → run id mapping for seeded demo runs                       */
/* ------------------------------------------------------------------ */

export const DEMO_RUN_MISSIONS: Record<string, string> = {
  "demo-run-1": "demo-mission-1",
  "demo-run-2": "demo-mission-2",
  "demo-run-3": "demo-mission-3",
};

export function seededReportForMission(missionId: string): Report | null {
  switch (missionId) {
    case "demo-mission-1":
      return DEMO_REPORTS["demo-run-1"];
    case "demo-mission-2":
      return DEMO_REPORTS["demo-run-2"];
    case "demo-mission-3":
      return DEMO_REPORTS["demo-run-3"];
    default:
      return null;
  }
}
