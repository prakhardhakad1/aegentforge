"use client";
/**
 * useRunStream — live-run state for /runs/[id].
 *
 * Strategy (per INTERFACES.md):
 *  1. Seed from GET /api/runs/{id} (RunSnapshot: run, mission, events so far,
 *     artifacts, token_usage, report).
 *  2. Subscribe to the pinned WS endpoint /api/runs/{id}/stream. On open the
 *     client sends {"type":"replay","after_seq":N}; every message is a pinned
 *     Event envelope. Events with seq <= lastSeq are dropped (dedup).
 *  3. If the WS drops, reconnect with exponential backoff (3 attempts) and
 *     poll GET /api/runs/{id}/events?after_seq=N every 2.5s in between and
 *     after exhaustion, so the view keeps advancing either way.
 *  4. Demo mode (NEXT_PUBLIC_DEMO_MODE=1 or API unreachable) bridges to the
 *     demo engine's simulated stream instead of opening a socket.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, demoActive, getRunStreamUrl } from "@/lib/api";
import {
  activeAgents,
  artifactsFromEvents,
  lastSeq,
  parseEvent,
  planFromEvents,
  statusFromEvents,
} from "@/lib/events";
import { ApiError } from "@/lib/types";
import {
  AGENT_ROLES,
  type AgentForgeEvent,
  type AgentRole,
  type Artifact,
  type Mission,
  type Report,
  type Run,
  type RunStatus,
  type RunSnapshot,
  type Subtask,
  type TokenUsage,
} from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Public state shape                                                  */
/* ------------------------------------------------------------------ */

export type ConnectionState =
  | "connecting"
  | "live"
  | "polling"
  | "demo"
  | "closed"
  | "error";

export interface AgentRuntimeState {
  role: AgentRole;
  /** idle → working → done */
  status: "idle" | "working" | "done";
  lastThought?: string;
  lastTool?: string;
  lastToolOk?: boolean;
  startedAt?: string;
  finishedAt?: string;
}

export interface RunStreamState {
  connection: ConnectionState;
  run: Run | null;
  mission: Mission | null;
  report: Report | null;
  status: RunStatus;
  events: AgentForgeEvent[];
  plan: Subtask[];
  artifacts: Artifact[];
  tokenUsage: TokenUsage;
  agents: Record<AgentRole, AgentRuntimeState>;
  reportReady: boolean;
  error: string | null;
}

const emptyTokenUsage: TokenUsage = {
  per_agent: {},
  totals: { input_tokens: 0, output_tokens: 0, cost_usd: 0 },
};

function initialAgents(): Record<AgentRole, AgentRuntimeState> {
  const out = {} as Record<AgentRole, AgentRuntimeState>;
  for (const r of AGENT_ROLES) {
    out[r] = { role: r, status: "idle" };
  }
  return out;
}

export const initialRunStreamState: RunStreamState = {
  connection: "connecting",
  run: null,
  mission: null,
  report: null,
  status: "queued",
  events: [],
  plan: [],
  artifacts: [],
  tokenUsage: emptyTokenUsage,
  agents: initialAgents(),
  reportReady: false,
  error: null,
};

/* ------------------------------------------------------------------ */
/* Reducer                                                             */
/* ------------------------------------------------------------------ */

type Action =
  | { kind: "seed"; snapshot: RunSnapshot }
  | { kind: "event"; event: AgentForgeEvent }
  | { kind: "connection"; value: ConnectionState }
  | { kind: "error"; message: string }
  | { kind: "reset" };

/** Fold a single event into the state (used for both seed and live events). */
function applyEvent(state: RunStreamState, e: AgentForgeEvent): RunStreamState {
  const next: RunStreamState = {
    ...state,
    events: [...state.events, e],
  };

  switch (e.type) {
    case "run_started": {
      if (next.status === "queued") next.status = "running";
      break;
    }
    case "plan_created": {
      next.plan = planFromEvents([e]);
      break;
    }
    case "agent_started": {
      const role = e.agent;
      if (role) {
        const prev = next.agents[role];
        next.agents = {
          ...next.agents,
          [role]: {
            ...prev,
            status: "working",
            startedAt: e.ts,
            lastThought: undefined,
            lastTool: undefined,
            lastToolOk: undefined,
          },
        };
      }
      break;
    }
    case "thought_summary": {
      const role = e.agent;
      if (role) {
        next.agents = {
          ...next.agents,
          [role]: { ...next.agents[role], lastThought: e.payload.summary },
        };
      }
      break;
    }
    case "tool_call": {
      const role = e.agent;
      if (role) {
        next.agents = {
          ...next.agents,
          [role]: { ...next.agents[role], lastTool: e.payload.tool, lastToolOk: e.payload.ok },
        };
      }
      break;
    }
    case "tool_result": {
      const role = e.agent;
      if (role) {
        next.agents = {
          ...next.agents,
          [role]: { ...next.agents[role], lastTool: e.payload.tool, lastToolOk: e.payload.ok },
        };
      }
      break;
    }
    case "artifact_created": {
      const p = e.payload;
      next.artifacts = [
        ...artifactsFromEvents([e], state.artifacts.filter((a) => a.id !== p.artifact_id)),
      ];
      break;
    }
    case "step_completed": {
      next.plan = next.plan.map((s) =>
        s.id === e.payload.subtask_id ? { ...s, status: "done" } : s,
      );
      break;
    }
    case "agent_finished": {
      const role = e.agent;
      if (role) {
        next.agents = {
          ...next.agents,
          [role]: { ...next.agents[role], status: "done", finishedAt: e.ts },
        };
      }
      next.plan = next.plan.map((s) => (s.agent === role ? { ...s, status: "done" } : s));
      break;
    }
    case "token_update": {
      const p = e.payload;
      const role = (AGENT_ROLES.includes(p.agent) ? p.agent : "planner") as AgentRole;
      const cur = next.tokenUsage.per_agent[role] ?? {
        input_tokens: 0,
        output_tokens: 0,
        cost_usd: 0,
      };
      const updated: TokenUsage = {
        per_agent: {
          ...next.tokenUsage.per_agent,
          [role]: {
            input_tokens: cur.input_tokens + (Number(p.input_tokens) || 0),
            output_tokens: cur.output_tokens + (Number(p.output_tokens) || 0),
            cost_usd: cur.cost_usd + (Number(p.cost_usd) || 0),
          },
        },
        totals: { ...next.tokenUsage.totals },
      };
      updated.totals.input_tokens += Number(p.input_tokens) || 0;
      updated.totals.output_tokens += Number(p.output_tokens) || 0;
      // run_total_usd is the authoritative cumulative figure when present.
      updated.totals.cost_usd =
        typeof p.run_total_usd === "number" && p.run_total_usd > 0
          ? p.run_total_usd
          : updated.totals.cost_usd + (Number(p.cost_usd) || 0);
      next.tokenUsage = updated;
      break;
    }
    case "run_finished": {
      next.status = "succeeded";
      next.reportReady = e.payload.report_ready !== false;
      break;
    }
    case "run_failed": {
      next.status = "failed";
      next.error = `${e.payload.error} (stage: ${e.payload.stage})`;
      break;
    }
    default:
      break;
  }
  return next;
}

function reducer(state: RunStreamState, action: Action): RunStreamState {
  switch (action.kind) {
    case "seed": {
      const snap = action.snapshot;
      let s: RunStreamState = {
        ...initialRunStreamState,
        run: snap.run,
        mission: snap.mission,
        report: snap.report ?? null,
        status: snap.run.status,
        tokenUsage: snap.token_usage ?? emptyTokenUsage,
        artifacts: Array.isArray(snap.artifacts) ? [...snap.artifacts] : [],
        agents: initialAgents(),
      };
      const seedEvents = [...snap.events].sort((a, b) => a.seq - b.seq);
      for (const e of seedEvents) s = applyEvent(s, e);
      // Seeded artifacts from the snapshot win over event-derived ones.
      if (snap.artifacts && snap.artifacts.length > 0) {
        const merged = artifactsFromEvents([], snap.artifacts);
        for (const a of artifactsFromEvents(seedEvents, [])) {
          if (!merged.some((m) => m.id === a.id)) merged.push(a);
        }
        s.artifacts = merged;
      }
      s = { ...s, status: statusFromEvents(seedEvents, snap.run.status) };
      return s;
    }
    case "event": {
      if (action.event.seq <= lastSeq(state.events)) return state;
      return applyEvent(state, action.event);
    }
    case "connection":
      return { ...state, connection: action.value };
    case "error":
      return { ...state, error: action.message };
    case "reset":
      return { ...initialRunStreamState, connection: "connecting" };
    default:
      return state;
  }
}

/* ------------------------------------------------------------------ */
/* Hook                                                                */
/* ------------------------------------------------------------------ */

export interface UseRunStreamResult extends RunStreamState {
  /** Roles currently mid-task (working but not finished). */
  activeRoles: Set<AgentRole>;
  /** Manually retry after an error (re-runs the whole effect). */
  retry: () => void;
}

function isTerminal(status: RunStatus): boolean {
  return status === "succeeded" || status === "failed" || status === "partial";
}

export function useRunStream(runId: string): UseRunStreamResult {
  const [state, dispatch] = useReducer(reducer, initialRunStreamState);
  const [nonce, setNonce] = useState(0);
  const lastSeqRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const retry = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    const cleanups: Array<() => void> = [];

    const stopPolling = () => {
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
    cleanups.push(stopPolling);

    const onEvent = (raw: unknown) => {
      if (stopped) return;
      const e = parseEvent(raw);
      if (!e) return; // pong / unknown control frames
      if (e.seq <= lastSeqRef.current) return;
      lastSeqRef.current = e.seq;
      dispatch({ kind: "event", event: e });
      if (e.type === "run_finished" || e.type === "run_failed") {
        stopPolling();
        dispatch({ kind: "connection", value: "closed" });
      }
    };

    /** Polling fallback: GET /api/runs/{id}/events?after_seq=N every 2.5s. */
    const startPolling = () => {
      if (pollTimerRef.current !== null || stopped) return;
      dispatch({ kind: "connection", value: "polling" });
      const tick = async () => {
        try {
          const res = await api.getRunEvents(runId, lastSeqRef.current);
          for (const e of res.events) onEvent(e);
        } catch {
          /* transient poll failures are invisible; next tick retries */
        }
      };
      void tick();
      pollTimerRef.current = setInterval(tick, 2500);
    };

    /** WS with reconnect + exponential backoff; polling fills the gaps. */
    const connectWs = (attempt: number) => {
      if (stopped) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(getRunStreamUrl(runId));
      } catch {
        handleDrop(attempt);
        return;
      }
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ type: "ping" }));
          } catch {
            /* socket closing */
          }
        }
      }, 30_000);

      ws.onopen = () => {
        if (stopped) return;
        stopPolling();
        dispatch({ kind: "connection", value: "live" });
        try {
          ws.send(JSON.stringify({ type: "replay", after_seq: lastSeqRef.current }));
        } catch {
          /* ignore */
        }
      };
      ws.onmessage = (msg) => {
        if (typeof msg.data !== "string") return;
        try {
          onEvent(JSON.parse(msg.data));
        } catch {
          /* non-JSON frame */
        }
      };
      const drop = () => {
        clearInterval(pingInterval);
        try {
          ws.close();
        } catch {
          /* already closed */
        }
        handleDrop(attempt);
      };
      ws.onerror = drop;
      ws.onclose = drop;
      cleanups.push(() => {
        clearInterval(pingInterval);
        try {
          ws.close();
        } catch {
          /* already closed */
        }
      });
    };

    const handleDrop = (attempt: number) => {
      if (stopped) return;
      startPolling(); // fills the gap while we (re)connect
      if (attempt < 3) {
        const backoff = 1200 * Math.pow(2, attempt);
        const t = setTimeout(() => {
          if (!stopped) connectWs(attempt + 1);
        }, backoff);
        cleanups.push(() => clearTimeout(t));
      }
      // After 3 failed attempts we stay in polling mode for this session.
    };

    const startStream = () => {
      if (demoActive()) {
        dispatch({ kind: "connection", value: "demo" });
        const off = api.subscribeRun(runId, onEvent);
        cleanups.push(off);
        return;
      }
      connectWs(0);
    };

    void (async () => {
      dispatch({ kind: "connection", value: "connecting" });
      try {
        const snap = await api.getRun(runId);
        if (stopped) return;
        lastSeqRef.current = lastSeq(snap.events ?? []);
        dispatch({ kind: "seed", snapshot: snap });
        if (isTerminal(snap.run.status)) {
          dispatch({ kind: "connection", value: "closed" });
          return;
        }
        startStream();
      } catch (err) {
        if (stopped) return;
        const message =
          err instanceof ApiError
            ? err.status === 404
              ? "Run not found. Check the URL or start a new mission."
              : `Could not load run: ${err.message}`
            : "Could not load run — the API is unreachable.";
        dispatch({ kind: "error", message });
        dispatch({ kind: "connection", value: "error" });
      }
    })();

    return () => {
      stopped = true;
      for (const fn of cleanups) {
        try {
          fn();
        } catch {
          /* cleanup must never throw */
        }
      }
      cleanups.length = 0;
      pollTimerRef.current = null;
    };
  }, [runId, nonce]);

  const activeRoles = useMemo(() => activeAgents(state.events), [state.events]);

  return { ...state, activeRoles, retry };
}

export default useRunStream;
