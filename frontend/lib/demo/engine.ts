/**
 * Demo engine — an in-memory mock of the AgentForge API.
 *
 * Active when NEXT_PUBLIC_DEMO_MODE=1 or when the live API is unreachable.
 * Holds missions/runs in a module-level store, simulates a run by emitting the
 * pinned event envelopes with realistic delays, and serves a full mock report.
 */
import type {
  AgentForgeEvent,
  Artifact,
  Dataset,
  Mission,
  N8nWorkflow,
  Report,
  Run,
  RunSnapshot,
  Subtask,
  Template,
  TemplatesList,
  TokenUsage,
} from "@/lib/types";
import { artifactsFromEvents, tokensFromEvents } from "@/lib/events";
import {
  DEMO_MISSIONS,
  DEMO_RUN_MISSIONS,
  DEMO_TOKEN_USAGE,
  DEMO_TEMPLATES,
  seededReportForMission,
} from "./data";
import { buildRunScript, planForMission, scriptToEvents, type ScriptedStep } from "./engine-script";

/* ------------------------------------------------------------------ */
/* Store types                                                         */
/* ------------------------------------------------------------------ */

type Listener = (event: AgentForgeEvent) => void;

interface DemoRunState {
  run: Run;
  mission: Mission;
  template: Template | null;
  plan: Subtask[];
  report: Report | null;
  script: ScriptedStep[];
  pos: number; // index of next scripted step to emit
  timer: ReturnType<typeof setTimeout> | null;
  listeners: Set<Listener>;
  done: boolean;
}

interface DemoStore {
  missions: Map<string, Mission>;
  runs: Map<string, DemoRunState>;
  datasets: Map<string, Dataset>;
  missionCounter: number;
  runCounter: number;
  datasetCounter: number;
}

declare global {
  interface Window {
    __agentforgeDemoStore?: DemoStore;
  }
}

function store(): DemoStore {
  if (typeof window !== "undefined") {
    if (!window.__agentforgeDemoStore) {
      window.__agentforgeDemoStore = {
        missions: new Map(),
        runs: new Map(),
        datasets: new Map(),
        missionCounter: 0,
        runCounter: 0,
        datasetCounter: 0,
      };
    }
    return window.__agentforgeDemoStore;
  }
  // SSR fallback (functions are only called client-side in practice).
  const g = globalThis as unknown as { __agentforgeDemoStoreSsr?: DemoStore };
  if (!g.__agentforgeDemoStoreSsr) {
    g.__agentforgeDemoStoreSsr = {
      missions: new Map(),
      runs: new Map(),
      datasets: new Map(),
      missionCounter: 0,
      runCounter: 0,
      datasetCounter: 0,
    };
  }
  return g.__agentforgeDemoStoreSsr;
}

/* ------------------------------------------------------------------ */
/* Seeded runs                                                         */
/* ------------------------------------------------------------------ */

const SEED_EPOCH = Date.UTC(2026, 9, 4, 9, 20, 0); // 2026-10-04T09:20:00Z

function getSeededRun(runId: string): DemoRunState | null {
  const missionId = DEMO_RUN_MISSIONS[runId];
  if (!missionId) return null;
  const mission = DEMO_MISSIONS.find((m) => m.id === missionId);
  if (!mission) return null;
  const template = DEMO_TEMPLATES.find((t) => t.id === mission.template_id) ?? null;
  const report = seededReportForMission(missionId);
  const startedAt = new Date(SEED_EPOCH + (Number(runId.slice(-1)) - 1) * 3600_000);
  const script = buildRunScript({ runId, mission, template, report });
  const seededEvents = scriptToEvents(runId, script, startedAt);
  const state: DemoRunState = {
    run: {
      id: runId,
      mission_id: missionId,
      status: "succeeded", // seeded demo runs all succeeded
      created_at: startedAt.toISOString(),
      finished_at: seededEvents[seededEvents.length - 1]?.ts ?? startedAt.toISOString(),
    },
    mission,
    template,
    plan: planForMission(mission, template),
    report,
    script,
    pos: script.length, // fully played already
    timer: null,
    listeners: new Set(),
    done: true,
  };
  return state;
}

/** Full event list for a run state (emitted so far). */
function eventsFor(state: DemoRunState): AgentForgeEvent[] {
  if (state.done) {
    return scriptToEvents(state.run.id, state.script, new Date(state.run.created_at));
  }
  const emitted = scriptToEvents(
    state.run.id,
    state.script.slice(0, state.pos),
    new Date(state.run.created_at),
  );
  return emitted;
}

function artifactsFor(state: DemoRunState): Artifact[] {
  return artifactsFromEvents(eventsFor(state));
}

function tokenUsageFor(state: DemoRunState): TokenUsage {
  const seeded = DEMO_TOKEN_USAGE[state.run.id];
  if (state.done && seeded) return seeded;
  const { perAgent, runTotalUsd } = tokensFromEvents(eventsFor(state));
  const totals = { input_tokens: 0, output_tokens: 0, cost_usd: 0 };
  for (const v of Object.values(perAgent)) {
    if (!v) continue;
    totals.input_tokens += v.input_tokens;
    totals.output_tokens += v.output_tokens;
  }
  if (runTotalUsd > 0) totals.cost_usd = runTotalUsd;
  else for (const v of Object.values(perAgent)) if (v) totals.cost_usd += v.cost_usd;
  totals.cost_usd = Math.round(totals.cost_usd * 10000) / 10000;
  return { per_agent: perAgent, totals };
}

function snapshotFor(state: DemoRunState): RunSnapshot {
  return {
    run: state.run,
    mission: state.mission,
    events: eventsFor(state),
    artifacts: artifactsFor(state),
    token_usage: tokenUsageFor(state),
    report: state.done ? state.report : null,
  };
}

/* ------------------------------------------------------------------ */
/* Simulation ticking                                                  */
/* ------------------------------------------------------------------ */

function emit(state: DemoRunState, event: AgentForgeEvent): void {
  for (const l of state.listeners) {
    try {
      l(event);
    } catch {
      // listener errors must never break the simulation
    }
  }
}

function scheduleNext(state: DemoRunState): void {
  if (state.pos >= state.script.length) {
    state.done = true;
    state.run.status = state.script.some((s) => s.type === "run_failed") ? "failed" : "succeeded";
    state.run.finished_at = new Date().toISOString();
    return;
  }
  if (typeof window === "undefined") return; // never tick during SSR
  const step = state.script[state.pos];
  state.timer = setTimeout(() => {
    // Re-evaluate: the step's timestamp is "now".
    const seq = state.pos + 1;
    const event = {
      type: step.type,
      run_id: state.run.id,
      seq,
      ts: new Date().toISOString(),
      agent: step.agent,
      payload: step.payload,
    } as AgentForgeEvent;
    state.pos += 1;
    if (event.type === "run_started") state.run.status = "running";
    emit(state, event);
    scheduleNext(state);
  }, Math.max(120, step.delayMs));
}

function startSimulation(state: DemoRunState): void {
  if (state.done || state.timer) return;
  state.run.status = "queued";
  scheduleNext(state);
}

/* ------------------------------------------------------------------ */
/* Access / lazily materialize runs                                    */
/* ------------------------------------------------------------------ */

function ensureRun(runId: string): DemoRunState {
  const s = store();
  const existing = s.runs.get(runId);
  if (existing) return existing;

  const seeded = getSeededRun(runId);
  if (seeded) {
    s.runs.set(runId, seeded);
    return seeded;
  }

  // Unknown id (e.g. judge typed a URL, or the app restarted): spin up a fresh
  // animating run for the flagship demo mission so the live view still works.
  const mission =
    s.missions.get("demo-mission-1") ??
    DEMO_MISSIONS[0];
  if (!s.missions.has(mission.id)) s.missions.set(mission.id, mission);
  const template = DEMO_TEMPLATES.find((t) => t.id === mission.template_id) ?? null;
  const report = seededReportForMission(mission.id) ?? DEMO_REPORT_FALLBACK;
  const state: DemoRunState = {
    run: {
      id: runId,
      mission_id: mission.id,
      status: "queued",
      created_at: new Date().toISOString(),
      finished_at: null,
    },
    mission,
    template,
    plan: planForMission(mission, template),
    report,
    script: buildRunScript({ runId, mission, template, report }),
    pos: 0,
    timer: null,
    listeners: new Set(),
    done: false,
  };
  s.runs.set(runId, state);
  startSimulation(state);
  return state;
}

/** Fallback generic report for dynamically created missions. */
const DEMO_REPORT_FALLBACK: Report = {
  title: "Mission Report",
  mission: DEMO_MISSIONS[0].goal,
  style: "default",
  executive_summary:
    "The team analyzed the goal, gathered context, ran the data analysis and stress-tested every claim. The full breakdown follows — strongest insights first.",
  insights: [
    {
      title: "The headline metric moves with one dominant segment",
      detail:
        "A single segment explains the majority of the change you asked about; the rest is noise. Focus effort where the mass is.",
      evidence: ["Segment analysis of the provided data", "Cross-check against external benchmarks"],
      strength: "high",
    },
    {
      title: "External context shifts the interpretation slightly",
      detail:
        "Industry benchmarks suggest part of the movement is market-wide rather than specific to your business.",
      evidence: ["Benchmark comparison from web research"],
      strength: "medium",
    },
  ],
  charts: [],
  predictions: [
    {
      claim: "The metric stabilizes within one quarter of applying the top recommendation.",
      confidence: 0.6,
      basis: "Trend continuation plus the modeled effect of the recommended fix.",
    },
  ],
  recommendations: [
    {
      title: "Act on the dominant segment first",
      action: "Target the segment that drives most of the movement with a dedicated fix within two weeks.",
      expected_impact: "Addresses the largest share of the observed change.",
      effort: "M",
      priority: 1,
    },
  ],
  appendix: "Demo-mode report for a dynamically created mission.",
};

/* ------------------------------------------------------------------ */
/* Public demo API (mirrors the real endpoints)                        */
/* ------------------------------------------------------------------ */

export interface CreateMissionInput {
  goal: string;
  template_id?: string | null;
  dataset_id?: string | null;
}

export function demoCreateMission(input: CreateMissionInput): Mission {
  const s = store();
  s.missionCounter += 1;
  const mission: Mission = {
    id: `demo-mission-new-${s.missionCounter}`,
    goal: input.goal,
    template_id: input.template_id ?? null,
    dataset_id: input.dataset_id ?? null,
    created_at: new Date().toISOString(),
  };
  s.missions.set(mission.id, mission);
  return mission;
}

export function demoListMissions(params?: { limit?: number; offset?: number }): { missions: Mission[]; total: number } {
  const s = store();
  for (const m of DEMO_MISSIONS) if (!s.missions.has(m.id)) s.missions.set(m.id, m);
  const all = [...s.missions.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const offset = params?.offset ?? 0;
  const limit = params?.limit ?? 50;
  return { missions: all.slice(offset, offset + limit), total: all.length };
}

export function demoGetMission(id: string): Mission {
  const s = store();
  const mission = s.missions.get(id) ?? DEMO_MISSIONS.find((m) => m.id === id);
  if (!mission) throw new Error(`Mission ${id} not found`);
  return mission;
}

export function demoStartRun(missionId: string, body?: { template_id?: string }): Run {
  const s = store();
  const mission = demoGetMission(missionId);
  s.runCounter += 1;
  const runId = `demo-run-new-${s.runCounter}`;
  const template = DEMO_TEMPLATES.find(
    (t) => t.id === (body?.template_id ?? mission.template_id),
  ) ?? null;
  const report = seededReportForMission(mission.id) ?? DEMO_REPORT_FALLBACK;
  const state: DemoRunState = {
    run: {
      id: runId,
      mission_id: missionId,
      status: "queued",
      created_at: new Date().toISOString(),
      finished_at: null,
    },
    mission,
    template,
    plan: planForMission(mission, template),
    report,
    script: buildRunScript({ runId, mission, template, report }),
    pos: 0,
    timer: null,
    listeners: new Set(),
    done: false,
  };
  s.runs.set(runId, state);
  startSimulation(state);
  return state.run;
}

export function demoGetRun(runId: string): RunSnapshot {
  const state = ensureRun(runId);
  return snapshotFor(state);
}

export function demoGetRunEvents(runId: string, afterSeq?: number): { events: AgentForgeEvent[] } {
  const state = ensureRun(runId);
  const events = eventsFor(state);
  return { events: afterSeq ? events.filter((e) => e.seq > afterSeq) : events };
}

export function demoGetTemplates(): TemplatesList {
  return { templates: DEMO_TEMPLATES };
}

export function demoSubscribeRun(runId: string, onEvent: Listener): () => void {
  const state = ensureRun(runId);
  // Replay everything already emitted (backlog), then stream live.
  for (const e of eventsFor(state)) onEvent(e);
  if (state.done) return () => undefined;
  const listener: Listener = onEvent;
  state.listeners.add(listener);
  return () => state.listeners.delete(listener);
}

/* ------------------------------------------------------------------ */
/* Demo CSV upload                                                     */
/* ------------------------------------------------------------------ */

function inferDtype(values: string[]): string {
  const nonEmpty = values.filter((v) => v !== "" && v !== null && v !== undefined);
  if (nonEmpty.length === 0) return "object";
  if (nonEmpty.every((v) => /^-?\d+$/.test(v.trim()))) return "int64";
  if (nonEmpty.every((v) => !Number.isNaN(Number(v)))) return "float64";
  if (nonEmpty.every((v) => !Number.isNaN(Date.parse(v)) && /\d{4}-\d{2}-\d{2}/.test(v))) return "datetime64[ns]";
  return "object";
}

function splitCsvLine(line: string, delim: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else inQuotes = !inQuotes;
    } else if (ch === delim && !inQuotes) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out.map((c) => c.trim());
}

export async function demoUploadDataset(file: File): Promise<Dataset> {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) {
    throw new Error("File needs a header row plus at least one data row.");
  }
  const first = lines[0];
  const delim = ["\t", ";", ","].find((d) => first.includes(d)) ?? ",";
  const columns = splitCsvLine(first, delim);
  const rows = lines.slice(1).map((l) => splitCsvLine(l, delim));
  const dtypes: Record<string, string> = {};
  columns.forEach((col, i) => {
    dtypes[col] = inferDtype(rows.map((r) => r[i] ?? ""));
  });
  const missing = columns.reduce((acc: string[], col: string, i: number) => {
    const n = rows.filter((r) => !r[i]).length;
    if (n > 0) acc.push(`${col}: ${n} missing`);
    return acc;
  }, [] as string[]);
  const qualityNotes: string[] = [];
  for (const m of missing) qualityNotes.push(`${m} values.`);
  if (rows.length > 5000) qualityNotes.push("Large file — stats computed on a sample of 5,000 rows.");
  if (columns.length < 2) qualityNotes.push("Only one column detected; segmentation will be limited.");
  if (qualityNotes.length === 0) qualityNotes.push("No obvious data-quality issues detected.");

  const s = store();
  s.datasetCounter += 1;
  const dataset: Dataset = {
    id: `demo-dataset-uploaded-${s.datasetCounter}`,
    filename: file.name,
    row_count: rows.length,
    columns,
    dtypes,
    preview: rows.slice(0, 20).map((r) =>
      columns.map((_, i) => {
        const raw = r[i] ?? "";
        const num = Number(raw);
        return raw !== "" && !Number.isNaN(num) ? num : raw || null;
      }),
    ),
    quality_notes: qualityNotes,
  };
  s.datasets.set(dataset.id, dataset);
  return dataset;
}

/* ------------------------------------------------------------------ */
/* Demo n8n export                                                     */
/* ------------------------------------------------------------------ */

export function demoExportN8n(runId: string): N8nWorkflow {
  const state = ensureRun(runId);
  const goal = state.mission.goal;
  return {
    name: `AgentForge — ${goal.slice(0, 60)}`,
    nodes: [
      {
        parameters: { path: `agentforge-${runId}`, httpMethod: "POST", responseMode: "lastNode" },
        id: "node-webhook",
        name: "Mission Webhook",
        type: "n8n-nodes-base.webhook",
        typeVersion: 1,
        position: [240, 300],
      },
      {
        parameters: {
          values: {
            string: [{ name: "mission_goal", value: goal }],
            string2: [{ name: "run_id", value: runId }],
          },
        },
        id: "node-set-mission",
        name: "Set Mission",
        type: "n8n-nodes-base.set",
        typeVersion: 1,
        position: [460, 300],
      },
      {
        parameters: {
          url: "http://localhost:8000/api/runs/{{ $json.run_id }}",
          options: {},
        },
        id: "node-fetch-run",
        name: "Fetch Run Snapshot",
        type: "n8n-nodes-base.httpRequest",
        typeVersion: 4,
        position: [680, 300],
      },
      {
        parameters: {
          jsCode:
            "// Fan the report out per section\nconst snapshot = $input.first().json;\nconst report = snapshot.report ?? {};\nreturn [\n  { json: { section: 'insights', items: report.insights ?? [] } },\n  { json: { section: 'predictions', items: report.predictions ?? [] } },\n  { json: { section: 'recommendations', items: report.recommendations ?? [] } },\n];",
        },
        id: "node-split",
        name: "Split Report Sections",
        type: "n8n-nodes-base.code",
        typeVersion: 2,
        position: [900, 300],
      },
      {
        parameters: {
          conditions: {
            string: [{ value1: "={{ $json.section }}", value2: "recommendations" }],
          },
        },
        id: "node-if",
        name: "Is Recommendations?",
        type: "n8n-nodes-base.if",
        typeVersion: 1,
        position: [1120, 300],
      },
      {
        parameters: { functionCode: "return items.map(i => ({ json: i.json }));" },
        id: "noop-true",
        name: "Notify Channel",
        type: "n8n-nodes-base.noOp",
        typeVersion: 1,
        position: [1340, 240],
      },
      {
        parameters: { functionCode: "return items.map(i => ({ json: i.json }));" },
        id: "noop-false",
        name: "Archive Section",
        type: "n8n-nodes-base.noOp",
        typeVersion: 1,
        position: [1340, 380],
      },
    ],
    connections: {
      "Mission Webhook": { main: [[{ node: "Set Mission", type: "main", index: 0 }]] },
      "Set Mission": { main: [[{ node: "Fetch Run Snapshot", type: "main", index: 0 }]] },
      "Fetch Run Snapshot": { main: [[{ node: "Split Report Sections", type: "main", index: 0 }]] },
      "Split Report Sections": { main: [[{ node: "Is Recommendations?", type: "main", index: 0 }]] },
      "Is Recommendations?": {
        main: [
          [{ node: "Notify Channel", type: "main", index: 0 }],
          [{ node: "Archive Section", type: "main", index: 0 }],
        ],
      },
    },
  };
}

