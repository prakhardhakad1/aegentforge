/**
 * AgentForge typed API client.
 *
 * - Mirrors every endpoint in docs/INTERFACES.md with full TypeScript types.
 * - Demo mode: when NEXT_PUBLIC_DEMO_MODE=1 (or the live API is unreachable),
 *   calls transparently fall back to the built-in demo engine in lib/demo/.
 * - The live base URL comes from NEXT_PUBLIC_API_BASE_URL (default
 *   http://localhost:8000); WebSocket base from NEXT_PUBLIC_API_WS_URL
 *   (default ws://localhost:8000).
 */
import type {
  AgentForgeEvent,
  Dataset,
  EventsList,
  Health,
  Mission,
  MissionsList,
  N8nWorkflow,
  Report,
  Run,
  RunSnapshot,
  TemplatesList,
} from "./types";
import { ApiError } from "./types";
import { parseEvent } from "./events";
import { downloadBlob } from "./utils";
import {
  demoCreateMission,
  demoExportN8n,
  demoGetMission,
  demoGetRun,
  demoGetRunEvents,
  demoGetTemplates,
  demoListMissions,
  demoStartRun,
  demoSubscribeRun,
  demoUploadDataset,
} from "./demo/engine";
import { renderMarkdown } from "./demo/markdown";
import { buildPdf, reportToPdfBlocks } from "./demo/minipdf";

/* ------------------------------------------------------------------ */
/* Configuration                                                       */
/* ------------------------------------------------------------------ */

const DEFAULT_API_BASE = "http://localhost:8000";
const DEFAULT_WS_BASE = "ws://localhost:8000";
/** Frontend-side upload guard (bytes); the backend enforces MAX_UPLOAD_MB. */
export const MAX_UPLOAD_MB = 10;

export function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_API_BASE;
}

export function getWsBase(): string {
  return process.env.NEXT_PUBLIC_API_WS_URL || DEFAULT_WS_BASE;
}

/** Pinned WS endpoint for a run. */
export function getRunStreamUrl(runId: string): string {
  const base = getWsBase().replace(/\/+$/, "");
  return `${base}/api/runs/${encodeURIComponent(runId)}/stream`;
}

/** Demo mode flag (env). */
export function isDemoMode(): boolean {
  const v = process.env.NEXT_PUBLIC_DEMO_MODE;
  return v === "1" || v === "true" || v === "yes";
}

/* ------------------------------------------------------------------ */
/* Demo-fallback tracking (so the UI can show an honest badge)         */
/* ------------------------------------------------------------------ */

type DemoStateListener = (demoActive: boolean) => void;
const demoStateListeners = new Set<DemoStateListener>();
let liveApiUnreachable = false;

function setLiveApiUnreachable(v: boolean): void {
  if (liveApiUnreachable === v) return;
  liveApiUnreachable = v;
  for (const l of demoStateListeners) {
    try {
      l(demoActive());
    } catch {
      /* ignore listener errors */
    }
  }
}

/** True when API calls are currently being served by the demo engine. */
export function demoActive(): boolean {
  return isDemoMode() || liveApiUnreachable;
}

/** Subscribe to demo-fallback state changes (for the header badge). */
export function onDemoStateChange(cb: DemoStateListener): () => void {
  demoStateListeners.add(cb);
  return () => demoStateListeners.delete(cb);
}

/* ------------------------------------------------------------------ */
/* Transport                                                           */
/* ------------------------------------------------------------------ */

const FETCH_TIMEOUT_MS = 8_000;

async function rawFetch(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    return await fetch(`${getApiBase()}${path}`, {
      cache: "no-store",
      signal: controller.signal,
      ...init,
    });
  } finally {
    clearTimeout(timer);
  }
}

/** True when the failure looks like "backend down / unreachable". */
function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError || (err instanceof DOMException && err.name === "AbortError");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await rawFetch(path, init);
  } catch (err) {
    if (isNetworkError(err)) {
      setLiveApiUnreachable(true);
      throw new ApiError("AgentForge API is unreachable", 0);
    }
    throw err;
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown; message?: unknown };
      if (typeof body?.detail === "string") message = body.detail;
      else if (typeof body?.message === "string") message = body.message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

/**
 * Run a call with demo fallback: in demo mode use the engine directly; in
 * live mode use the network, and if the backend is unreachable, degrade to the
 * demo engine so the product keeps working offline.
 */
async function withFallback<T>(path: string, init: RequestInit | undefined, demo: () => T | Promise<T>): Promise<T> {
  if (isDemoMode()) return demo();
  try {
    return await request<T>(path, init);
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      return demo();
    }
    throw err;
  }
}

/* ------------------------------------------------------------------ */
/* Normalizers (defensive parsing of backend responses)                */
/* ------------------------------------------------------------------ */

function normalizeEvents(events: unknown): AgentForgeEvent[] {
  if (!Array.isArray(events)) return [];
  return events.map(parseEvent).filter((e): e is AgentForgeEvent => e !== null);
}

function normalizeRunSnapshot(raw: unknown): RunSnapshot {
  const r = (raw ?? {}) as Record<string, unknown>;
  const run = (r.run ?? {}) as Record<string, unknown>;
  const mission = (r.mission ?? {}) as Record<string, unknown>;
  return {
    run: {
      id: String(run.id ?? ""),
      mission_id: String(run.mission_id ?? ""),
      status: (run.status ?? "queued") as RunSnapshot["run"]["status"],
      created_at: String(run.created_at ?? ""),
      finished_at: (run.finished_at ?? null) as string | null,
    },
    mission: {
      id: String(mission.id ?? ""),
      goal: String(mission.goal ?? ""),
      template_id: (mission.template_id ?? null) as string | null,
      dataset_id: (mission.dataset_id ?? null) as string | null,
      created_at: String(mission.created_at ?? ""),
    },
    events: normalizeEvents(r.events),
    artifacts: Array.isArray(r.artifacts) ? (r.artifacts as RunSnapshot["artifacts"]) : [],
    token_usage: (r.token_usage ?? { per_agent: {}, totals: { input_tokens: 0, output_tokens: 0, cost_usd: 0 } }) as RunSnapshot["token_usage"],
    report: (r.report ?? null) as Report | null,
  };
}

/* ------------------------------------------------------------------ */
/* API surface                                                         */
/* ------------------------------------------------------------------ */

export interface CreateMissionInput {
  goal: string;
  template_id?: string | null;
  dataset_id?: string | null;
}

export interface StartRunInput {
  template_id?: string | null;
}

export type ReportFormat = "markdown" | "pdf";

export const api = {
  /** POST /api/missions */
  async createMission(input: CreateMissionInput): Promise<Mission> {
    return withFallback<Mission>(
      "/api/missions",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal: input.goal,
          template_id: input.template_id ?? null,
          dataset_id: input.dataset_id ?? null,
        }),
      },
      () => demoCreateMission(input),
    );
  },

  /** GET /api/missions?limit&offset */
  async listMissions(params?: { limit?: number; offset?: number }): Promise<MissionsList> {
    const qs = new URLSearchParams();
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return withFallback<MissionsList>(`/api/missions${suffix}`, undefined, () =>
      demoListMissions(params),
    );
  },

  /** GET /api/missions/{id} */
  async getMission(id: string): Promise<Mission> {
    return withFallback<Mission>(
      `/api/missions/${encodeURIComponent(id)}`,
      undefined,
      () => demoGetMission(id),
    );
  },

  /** POST /api/missions/{id}/runs */
  async startRun(missionId: string, body?: StartRunInput): Promise<Run> {
    return withFallback<Run>(
      `/api/missions/${encodeURIComponent(missionId)}/runs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      },
      () => demoStartRun(missionId, { template_id: body?.template_id ?? undefined }),
    );
  },

  /** GET /api/runs/{id} */
  async getRun(runId: string): Promise<RunSnapshot> {
    return withFallback<RunSnapshot>(
      `/api/runs/${encodeURIComponent(runId)}`,
      undefined,
      () => demoGetRun(runId),
    ).then(normalizeRunSnapshot);
  },

  /** GET /api/runs/{id}/events?after_seq=N (polling fallback) */
  async getRunEvents(runId: string, afterSeq?: number): Promise<EventsList> {
    const qs = afterSeq !== undefined ? `?after_seq=${afterSeq}` : "";
    return withFallback<{ events: unknown }>(
      `/api/runs/${encodeURIComponent(runId)}/events${qs}`,
      undefined,
      () => demoGetRunEvents(runId, afterSeq),
    ).then((res) => ({ events: normalizeEvents(res.events) }));
  },

  /** POST /api/upload (multipart, .csv) */
  async uploadDataset(file: File): Promise<Dataset> {
    if (isDemoMode()) return demoUploadDataset(file);
    const form = new FormData();
    form.append("file", file);
    try {
      return await request<Dataset>("/api/upload", { method: "POST", body: form });
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) return demoUploadDataset(file);
      throw err;
    }
  },

  /** GET /api/templates */
  async getTemplates(): Promise<TemplatesList> {
    return withFallback<TemplatesList>("/api/templates", undefined, () => demoGetTemplates());
  },

  /** POST /api/runs/{id}/export/n8n */
  async exportN8n(runId: string): Promise<N8nWorkflow> {
    return withFallback<N8nWorkflow>(
      `/api/runs/${encodeURIComponent(runId)}/export/n8n`,
      { method: "POST" },
      () => demoExportN8n(runId),
    );
  },

  /** GET /healthz */
  async getHealth(): Promise<Health> {
    if (isDemoMode()) return { status: "ok" };
    try {
      return await request<Health>("/healthz");
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) return { status: "ok" };
      throw err;
    }
  },

  /** Same-origin URL for report downloads (proxied by next.config rewrites). */
  reportUrl(runId: string, format: ReportFormat): string {
    return `/api/runs/${encodeURIComponent(runId)}/report?format=${format}`;
  },

  /**
   * Download the run report. Live mode: fetches the pinned
   * GET /api/runs/{id}/report?format=markdown|pdf endpoint (as a Blob, same
   * origin via next.config rewrites). Demo mode: renders client-side.
   */
  async downloadReport(runId: string, format: ReportFormat, report?: Report | null): Promise<void> {
    const ext = format === "pdf" ? "pdf" : "md";
    const filename = `agentforge-report-${runId}.${ext}`;
    if (isDemoMode()) {
      const rep =
        report ??
        demoGetRun(runId).report ??
        ({ title: "Report", mission: "", style: "default", executive_summary: "", insights: [], charts: [], predictions: [], recommendations: [] } as Report);
      if (format === "markdown") {
        downloadBlob(new Blob([renderMarkdown(rep)], { type: "text/markdown;charset=utf-8" }), filename);
      } else {
        downloadBlob(new Blob([buildPdf(reportToPdfBlocks(rep))], { type: "application/pdf" }), filename);
      }
      return;
    }
    try {
      const res = await fetch(api.reportUrl(runId, format), { cache: "no-store" });
      if (!res.ok) throw new ApiError(`Report download failed (${res.status})`, res.status);
      downloadBlob(await res.blob(), filename);
    } catch (err) {
      if (err instanceof TypeError || (err instanceof DOMException && err.name === "AbortError")) {
        // Backend unreachable — fall back to client-side rendering.
        const rep = report ?? null;
        if (!rep) throw new ApiError("Report not available offline yet", 0);
        if (format === "markdown") {
          downloadBlob(new Blob([renderMarkdown(rep)], { type: "text/markdown;charset=utf-8" }), filename);
        } else {
          downloadBlob(new Blob([buildPdf(reportToPdfBlocks(rep))], { type: "application/pdf" }), filename);
        }
        return;
      }
      throw err;
    }
  },

  /**
   * Live run stream subscription. In demo mode this bridges to the demo
   * engine; in live mode the caller should open the WS from
   * getRunStreamUrl(runId) — see hooks/useRunStream.ts.
   */
  subscribeRun(runId: string, onEvent: (e: AgentForgeEvent) => void): () => void {
    return demoSubscribeRun(runId, onEvent);
  },
};

export default api;
