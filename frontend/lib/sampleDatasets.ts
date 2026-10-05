/**
 * Sample-dataset chips for /new. Each chip carries a small generated CSV so
 * the "upload" path exercises the REAL POST /api/upload endpoint in live mode
 * (and the demo parser in demo mode) — no backend sample-file endpoint needed.
 * Rows are deterministic (seeded PRNG) so demos are reproducible.
 */

export interface SampleDatasetChip {
  id: string;
  label: string;
  description: string;
  goal: string;
  templateId: string;
  filename: string;
  buildCsv: () => string;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(rand: () => number, arr: T[]): T {
  return arr[Math.floor(rand() * arr.length)];
}

/* ------------------------------ churn sample ----------------------------- */

function churnCsv(): string {
  const rand = mulberry32(42);
  const plans: Array<[string, number, number]> = [
    ["starter", 29, 0.42],
    ["pro", 99, 0.38],
    ["business", 299, 0.2],
  ];
  const rows = ["customer_id,plan,monthly_spend,logins_per_week,tickets_opened,churned"];
  for (let i = 0; i < 48; i++) {
    const r = rand();
    let acc = 0;
    let plan = plans[0];
    for (const p of plans) {
      acc += p[2];
      if (r <= acc) {
        plan = p;
        break;
      }
    }
    const churnChance = plan[0] === "starter" ? 0.34 : plan[0] === "pro" ? 0.16 : 0.06;
    const churned = rand() < churnChance ? 1 : 0;
    const logins = churned ? Math.floor(rand() * 3) : 2 + Math.floor(rand() * 14);
    const tickets = churned ? Math.floor(rand() * 5) : Math.floor(rand() * 2.4);
    rows.push(`CU-${1000 + i},${plan[0]},${plan[1]},${logins},${tickets},${churned}`);
  }
  return rows.join("\n");
}

/* ----------------------------- support sample ---------------------------- */

function supportCsv(): string {
  const rand = mulberry32(7);
  const themes = ["billing", "sso_login", "csv_export", "api_limits", "onboarding", "other"];
  const weights = [0.3, 0.24, 0.16, 0.13, 0.1, 0.07];
  const rows = ["ticket_id,created_at,theme,first_response_hours,resolved,csat"];
  for (let i = 0; i < 60; i++) {
    let acc = 0;
    let theme = themes[0];
    const r = rand();
    for (let t = 0; t < themes.length; t++) {
      acc += weights[t];
      if (r <= acc) {
        theme = themes[t];
        break;
      }
    }
    const resp = theme === "sso_login" ? 24 + rand() * 30 : 2 + rand() * 14;
    const resolved = rand() < (theme === "sso_login" ? 0.76 : 0.93) ? 1 : 0;
    const csat = resolved ? (resp > 20 ? 2 + rand() * 1.5 : 3 + rand() * 2).toFixed(1) : "";
    const day = 1 + Math.floor(rand() * 28);
    const hour = Math.floor(rand() * 12) + 7;
    rows.push(
      `TK-${5500 + i},2026-09-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:12:00Z,${theme},${resp.toFixed(1)},${resolved},${csat}`,
    );
  }
  return rows.join("\n");
}

/* ----------------------------- pipeline sample --------------------------- */

function pipelineCsv(): string {
  const rand = mulberry32(99);
  const stages = ["discovery", "demo", "proposal", "negotiation", "closed_won", "closed_lost"];
  const sources = ["inbound", "outbound", "partner", "event"];
  const rows = ["deal_id,stage,value_usd,source,days_in_stage,rep"];
  for (let i = 0; i < 55; i++) {
    const stage = pick(rand, stages);
    const value = Math.round((4 + rand() * 96) * 1000);
    const days = stage.startsWith("closed") ? Math.floor(rand() * 30) : 3 + Math.floor(rand() * 60);
    rows.push(`DL-${400 + i},${stage},${value},${pick(rand, sources)},${days},rep-${1 + Math.floor(rand() * 5)}`);
  }
  return rows.join("\n");
}

/* ------------------------------ survey sample ---------------------------- */

function surveyCsv(): string {
  const rand = mulberry32(2026);
  const segments = ["smb", "mid_market", "enterprise"];
  const regions = ["DE", "AT", "CH", "NL", "FR"];
  const rows = ["respondent_id,segment,region,seat_count,willingness_to_pay_eur,eu_hosting_required"];
  for (let i = 0; i < 45; i++) {
    const seg = pick(rand, segments);
    const seats = seg === "smb" ? 2 + Math.floor(rand() * 20) : seg === "mid_market" ? 21 + Math.floor(rand() * 100) : 120 + Math.floor(rand() * 400);
    const wtp = seg === "smb" ? 15 + rand() * 30 : seg === "mid_market" ? 40 + rand() * 120 : 150 + rand() * 400;
    rows.push(
      `RS-${300 + i},${seg},${pick(rand, regions)},${seats},${wtp.toFixed(0)},${rand() < 0.68 ? "yes" : "no"}`,
    );
  }
  return rows.join("\n");
}

export const SAMPLE_DATASET_CHIPS: SampleDatasetChip[] = [
  {
    id: "saas_churn",
    label: "SaaS churn",
    description: "Subscribers: plan, spend, usage, tickets, churn flag.",
    goal: "Analyze why our churn spiked in Q3 and recommend 3 fixes with expected impact.",
    templateId: "sales_insights_team",
    filename: "q3_subscribers_sample.csv",
    buildCsv: churnCsv,
  },
  {
    id: "support_tickets",
    label: "Support tickets",
    description: "One month of tickets: theme, response time, CSAT.",
    goal: "Triage last month's support tickets: top 5 themes and what to automate first.",
    templateId: "support_triage_team",
    filename: "support_tickets_sample.csv",
    buildCsv: supportCsv,
  },
  {
    id: "pipeline",
    label: "Sales pipeline",
    description: "Deals: stage, value, source, days in stage.",
    goal: "Which pipeline stage leaks the most revenue this quarter, and what should we fix first?",
    templateId: "sales_insights_team",
    filename: "sales_pipeline_sample.csv",
    buildCsv: pipelineCsv,
  },
  {
    id: "market_survey",
    label: "Market survey",
    description: "Survey: segment, region, seats, willingness to pay.",
    goal: "Should we expand into the DACH market this year? Size it and name the top 3 risks.",
    templateId: "market_research_team",
    filename: "market_survey_sample.csv",
    buildCsv: surveyCsv,
  },
];

export function sampleChipById(id: string): SampleDatasetChip | undefined {
  return SAMPLE_DATASET_CHIPS.find((c) => c.id === id);
}
