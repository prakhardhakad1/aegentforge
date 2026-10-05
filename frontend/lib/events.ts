/**
 * Event helpers: parse raw envelopes into the typed discriminated union and
 * derive UI state (labels, per-agent progress, artifact accumulation).
 */
import {
  AGENT_ROLES,
  EVENT_TYPES,
  type AgentForgeEvent,
  type AgentRole,
  type Artifact,
  type ArtifactCreatedPayload,
  type EventType,
  type RunStatus,
  type Subtask,
  type TokenUpdatePayload,
} from "./types";

/* ------------------------------------------------------------------ */
/* Parsing                                                             */
/* ------------------------------------------------------------------ */

/** Parse an unknown value into an AgentForgeEvent. Returns null if invalid. */
export function parseEvent(raw: unknown): AgentForgeEvent | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const type = typeof r.type === "string" ? (r.type as EventType) : null;
  if (!type || !EVENT_TYPES.includes(type)) return null;
  const agent =
    typeof r.agent === "string" && AGENT_ROLES.includes(r.agent as AgentRole)
      ? (r.agent as AgentRole)
      : null;
  const seq = typeof r.seq === "number" ? r.seq : Number(r.seq);
  const event = {
    type,
    run_id: typeof r.run_id === "string" ? r.run_id : "",
    seq: Number.isFinite(seq) ? seq : 0,
    ts: typeof r.ts === "string" ? r.ts : new Date().toISOString(),
    agent,
    payload: (r.payload && typeof r.payload === "object" ? r.payload : {}) as Record<string, unknown>,
  };
  return event as AgentForgeEvent;
}

/** Parse an array of raw envelopes, dropping invalid entries. */
export function parseEvents(raw: unknown[]): AgentForgeEvent[] {
  return raw.map(parseEvent).filter((e): e is AgentForgeEvent => e !== null);
}

/** Sort events by seq (stable, ascending). */
export function sortEvents(events: AgentForgeEvent[]): AgentForgeEvent[] {
  return [...events].sort((a, b) => a.seq - b.seq);
}

/** Merge two event lists by seq, keeping the highest-seq copy. */
export function mergeEvents(a: AgentForgeEvent[], b: AgentForgeEvent[]): AgentForgeEvent[] {
  const bySeq = new Map<number, AgentForgeEvent>();
  for (const e of [...a, ...b]) bySeq.set(e.seq, e);
  return sortEvents([...bySeq.values()]);
}

/** Human label per event type. */
export const EVENT_LABELS: Record<EventType, string> = {
  run_started: "Run started",
  plan_created: "Plan created",
  agent_started: "Agent started",
  thought_summary: "Thought",
  tool_call: "Tool call",
  tool_result: "Tool result",
  artifact_created: "Artifact",
  step_completed: "Step completed",
  agent_finished: "Agent finished",
  run_finished: "Run finished",
  run_failed: "Run failed",
  token_update: "Tokens",
};

/* ------------------------------------------------------------------ */
/* Derived state                                                       */
/* ------------------------------------------------------------------ */

/** Extract the plan subtasks from a `plan_created` event, if present. */
export function planFromEvents(events: AgentForgeEvent[]): Subtask[] {
  for (const e of events) {
    if (e.type === "plan_created") {
      const subtasks = (e.payload as { subtasks?: unknown }).subtasks;
      if (Array.isArray(subtasks)) {
        return subtasks.map((s, i) => {
          const rec = (s ?? {}) as Record<string, unknown>;
          return {
            id: String(rec.id ?? `st_${i}`),
            title: String(rec.title ?? "Untitled step"),
            agent: (AGENT_ROLES.includes(rec.agent as AgentRole)
              ? rec.agent
              : "planner") as AgentRole,
            depends_on: Array.isArray(rec.depends_on) ? rec.depends_on.map(String) : [],
            status: String(rec.status ?? "pending"),
          };
        });
      }
    }
  }
  return [];
}

/**
 * Accumulate per-agent token usage from `token_update` events.
 * `input_tokens`/`output_tokens`/`cost_usd` are treated as deltas per update;
 * `run_total_usd` (cumulative) is used as the authoritative run total when present.
 */
export function tokensFromEvents(events: AgentForgeEvent[]): {
  perAgent: Partial<Record<AgentRole, { input_tokens: number; output_tokens: number; cost_usd: number }>>;
  runTotalUsd: number;
} {
  const perAgent: Partial<Record<AgentRole, { input_tokens: number; output_tokens: number; cost_usd: number }>> = {};
  let runTotalUsd = 0;
  for (const e of events) {
    if (e.type !== "token_update") continue;
    const p = e.payload as TokenUpdatePayload;
    const role = (AGENT_ROLES.includes(p.agent) ? p.agent : "planner") as AgentRole;
    const cur = perAgent[role] ?? { input_tokens: 0, output_tokens: 0, cost_usd: 0 };
    perAgent[role] = {
      input_tokens: cur.input_tokens + (Number(p.input_tokens) || 0),
      output_tokens: cur.output_tokens + (Number(p.output_tokens) || 0),
      cost_usd: cur.cost_usd + (Number(p.cost_usd) || 0),
    };
    if (typeof p.run_total_usd === "number") runTotalUsd = p.run_total_usd;
  }
  return { perAgent, runTotalUsd };
}

/**
 * Build the artifact list from `artifact_created` events, optionally merging
 * artifacts already known from the run snapshot (dedup by id).
 */
export function artifactsFromEvents(
  events: AgentForgeEvent[],
  known: Artifact[] = [],
): Artifact[] {
  const byId = new Map<string, Artifact>();
  for (const a of known) byId.set(a.id, a);
  for (const e of events) {
    if (e.type !== "artifact_created") continue;
    const p = e.payload as ArtifactCreatedPayload;
    byId.set(p.artifact_id, {
      id: p.artifact_id,
      kind: p.kind,
      name: p.name,
      summary: p.summary,
      path: p.path ?? null,
      subtask_id: p.subtask_id ?? null,
      created_at: e.ts,
      data: null,
    });
  }
  return [...byId.values()];
}

/** Highest seq seen in a list (0 when empty). */
export function lastSeq(events: AgentForgeEvent[]): number {
  let max = 0;
  for (const e of events) if (e.seq > max) max = e.seq;
  return max;
}

/** Derive a UI run status from events (overrides snapshot status when terminal). */
export function statusFromEvents(events: AgentForgeEvent[], fallback: RunStatus): RunStatus {
  let status = fallback;
  for (const e of events) {
    if (e.type === "run_started" && status === "queued") status = "running";
    if (e.type === "run_finished") status = "succeeded";
    if (e.type === "run_failed") status = "failed";
  }
  return status;
}

/** Roles that have started but not finished — used to show "working" state. */
export function activeAgents(events: AgentForgeEvent[]): Set<AgentRole> {
  const started = new Set<AgentRole>();
  const finished = new Set<AgentRole>();
  for (const e of events) {
    if (!e.agent) continue;
    if (e.type === "agent_started") started.add(e.agent);
    if (e.type === "agent_finished") finished.add(e.agent);
  }
  const active = new Set<AgentRole>();
  for (const r of started) if (!finished.has(r)) active.add(r);
  return active;
}
