/**
 * AgentForge — canonical frontend types.
 *
 * Every shape here mirrors docs/INTERFACES.md exactly. Do not rename fields:
 * the backend (Agent 2), orchestrator (Agent 3/6) and demo engine all speak
 * these exact strings.
 */

/* ------------------------------------------------------------------ */
/* Enum-like string unions (exact strings pinned in INTERFACES.md)     */
/* ------------------------------------------------------------------ */

export type AgentRole = "planner" | "researcher" | "analyst" | "forecaster" | "critic";

export const AGENT_ROLES: AgentRole[] = [
  "planner",
  "researcher",
  "analyst",
  "forecaster",
  "critic",
];

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "partial";

export type ArtifactKind =
  | "chart"
  | "table"
  | "text"
  | "prediction"
  | "recommendation"
  | "report_markdown"
  | "report_pdf"
  | "file";

export const ARTIFACT_KINDS: ArtifactKind[] = [
  "chart",
  "table",
  "text",
  "prediction",
  "recommendation",
  "report_markdown",
  "report_pdf",
  "file",
];

export type EventType =
  | "run_started"
  | "plan_created"
  | "agent_started"
  | "thought_summary"
  | "tool_call"
  | "tool_result"
  | "artifact_created"
  | "step_completed"
  | "agent_finished"
  | "run_finished"
  | "run_failed"
  | "token_update";

export const EVENT_TYPES: EventType[] = [
  "run_started",
  "plan_created",
  "agent_started",
  "thought_summary",
  "tool_call",
  "tool_result",
  "artifact_created",
  "step_completed",
  "agent_finished",
  "run_finished",
  "run_failed",
  "token_update",
];

export type InsightStrength = "high" | "medium" | "low";
export type Effort = "S" | "M" | "L";
export type ReportStyle = "default" | "market_research" | "sales_insights" | "support_triage";

/* ------------------------------------------------------------------ */
/* Event envelope (WS + DB + frontend — canonical)                     */
/* ------------------------------------------------------------------ */

export interface EventBase {
  run_id: string;
  /** Monotonic per run, starts at 1. */
  seq: number;
  /** ISO-8601 UTC timestamp. */
  ts: string;
  /** Agent role or null. */
  agent: AgentRole | null;
}

export interface Subtask {
  id: string;
  title: string;
  agent: AgentRole;
  depends_on: string[];
  status: string;
}

export interface PlanCreatedPayload {
  subtasks: Subtask[];
}

export interface AgentStartedPayload {
  subtask_id: string;
  title: string;
}

export interface ThoughtSummaryPayload {
  subtask_id: string;
  summary: string;
}

/** Shared by `tool_call` and `tool_result`. */
export interface ToolPayload {
  subtask_id: string;
  tool: string;
  args_summary: string;
  ok: boolean;
}

export interface ArtifactCreatedPayload {
  subtask_id: string;
  artifact_id: string;
  kind: ArtifactKind;
  name: string;
  summary: string;
  path?: string;
}

export interface StepCompletedPayload {
  subtask_id: string;
}

export interface TokenUpdatePayload {
  agent: AgentRole;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  run_total_usd: number;
}

export interface RunFinishedPayload {
  report_ready: boolean;
}

export interface RunFailedPayload {
  error: string;
  stage: string;
}

export interface EmptyPayload {
  [key: string]: unknown;
}

export type AgentForgeEvent =
  | (EventBase & { type: "run_started"; payload: EmptyPayload })
  | (EventBase & { type: "plan_created"; payload: PlanCreatedPayload })
  | (EventBase & { type: "agent_started"; payload: AgentStartedPayload })
  | (EventBase & { type: "thought_summary"; payload: ThoughtSummaryPayload })
  | (EventBase & { type: "tool_call"; payload: ToolPayload })
  | (EventBase & { type: "tool_result"; payload: ToolPayload })
  | (EventBase & { type: "artifact_created"; payload: ArtifactCreatedPayload })
  | (EventBase & { type: "step_completed"; payload: StepCompletedPayload })
  | (EventBase & { type: "agent_finished"; payload: EmptyPayload })
  | (EventBase & { type: "run_finished"; payload: RunFinishedPayload })
  | (EventBase & { type: "run_failed"; payload: RunFailedPayload })
  | (EventBase & { type: "token_update"; payload: TokenUpdatePayload });

/** Client → WS messages (per INTERFACES.md). */
export type RunStreamClientMessage =
  | { type: "replay"; after_seq: number }
  | { type: "ping" };

/* ------------------------------------------------------------------ */
/* Core resource shapes                                                */
/* ------------------------------------------------------------------ */

export interface Mission {
  id: string;
  goal: string;
  template_id?: string | null;
  dataset_id?: string | null;
  created_at: string;
}

export interface Run {
  id: string;
  mission_id: string;
  status: RunStatus;
  created_at: string;
  finished_at?: string | null;
}

export interface MissionsList {
  missions: Mission[];
  total: number;
}

export interface EventsList {
  events: AgentForgeEvent[];
}

/* ------------------------------------------------------------------ */
/* Artifacts / charts                                                  */
/* ------------------------------------------------------------------ */

export interface ChartPoint {
  label: string;
  x: number;
  y: number;
}

export interface ChartSpec {
  id: string;
  kind: "bar" | "line" | "scatter" | "pie";
  title: string;
  x_label: string;
  y_label: string;
  data: ChartPoint[];
  notes?: string;
}

/** Loose payload for `table` artifacts (frontend-tolerant, may be absent). */
export interface TableData {
  columns: string[];
  rows: (string | number | null)[][];
}

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  name: string;
  summary: string;
  path?: string | null;
  subtask_id?: string | null;
  created_at?: string | null;
  /** Optional structured payload (e.g. ChartSpec for `chart` artifacts). */
  data?: ChartSpec | TableData | null;
}

/* ------------------------------------------------------------------ */
/* Tokens / cost                                                       */
/* ------------------------------------------------------------------ */

export interface AgentTokenUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TokenUsage {
  per_agent: Partial<Record<AgentRole, AgentTokenUsage>>;
  totals: AgentTokenUsage;
}

/* ------------------------------------------------------------------ */
/* Report (canonical, produced by orchestrator.report)                 */
/* ------------------------------------------------------------------ */

export interface Insight {
  title: string;
  detail: string;
  evidence: string[];
  strength: InsightStrength;
}

export interface Prediction {
  claim: string;
  /** 0..1 */
  confidence: number;
  basis: string;
}

export interface Recommendation {
  title: string;
  action: string;
  expected_impact: string;
  effort: Effort;
  /** 1 = do first. */
  priority: number;
}

export interface Report {
  title: string;
  mission: string;
  style: ReportStyle;
  executive_summary: string;
  /** Ranked: strongest first. */
  insights: Insight[];
  charts: ChartSpec[];
  predictions: Prediction[];
  recommendations: Recommendation[];
  appendix?: string;
}

/* ------------------------------------------------------------------ */
/* Templates                                                           */
/* ------------------------------------------------------------------ */

export interface TeamMember {
  role: AgentRole;
  title: string;
  system_prompt: string;
}

export interface DagNode {
  id: string;
  title: string;
  agent: AgentRole;
  depends_on: string[];
}

export interface Template {
  id: string;
  name: string;
  description: string;
  tags: string[];
  team: TeamMember[];
  planner_prompt: string;
  sample_mission: string;
  expected_dag: DagNode[];
  report_outline: string[];
}

export interface TemplatesList {
  templates: Template[];
}

/** Exact template ids pinned in INTERFACES.md. */
export const TEMPLATE_IDS = {
  MARKET_RESEARCH: "market_research_team",
  SALES_INSIGHTS: "sales_insights_team",
  SUPPORT_TRIAGE: "support_triage_team",
} as const;

/* ------------------------------------------------------------------ */
/* Datasets (POST /api/upload response)                                */
/* ------------------------------------------------------------------ */

export type DatasetCell = string | number | null;

export interface Dataset {
  id: string;
  filename: string;
  row_count: number;
  columns: string[];
  dtypes: Record<string, string>;
  /** Up to 20 preview rows (per INTERFACES.md). */
  preview: DatasetCell[][];
  quality_notes: string[];
}

/* ------------------------------------------------------------------ */
/* Run snapshot (GET /api/runs/{id})                                   */
/* ------------------------------------------------------------------ */

export interface RunSnapshot {
  run: Run;
  mission: Mission;
  events: AgentForgeEvent[];
  artifacts: Artifact[];
  token_usage: TokenUsage;
  report?: Report | null;
}

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */

export interface Health {
  status: string;
}

/** n8n workflow JSON (POST /api/runs/{id}/export/n8n). */
export interface N8nWorkflow {
  name: string;
  nodes: Record<string, unknown>[];
  connections: Record<string, unknown>;
  [key: string]: unknown;
}

/** API error shape surfaced by lib/api.ts. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
