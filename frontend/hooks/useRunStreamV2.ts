"use client";
/**
 * useRunStreamV2 — additive upgrade over hooks/useRunStream.ts (Agent 1).
 *
 * Agent 1's hook is kept as the engine (seeding, WS + replay, dedup, polling
 * fallback, demo bridge — all pinned-envelope logic). V2 wraps it and only
 * adds what it genuinely improves:
 *
 * 1. **Artifact data enrichment.** `artifactsFromEvents` (lib/events.ts) sets
 *    `data: null` on event-derived artifacts, so rich `artifact_created`
 *    payloads — a ChartSpec for kind=chart, `{columns, rows}` for kind=table,
 *    `{markdown}` for report_markdown — never reach ArtifactFeed's inline
 *    chart/table previews. V2 re-attaches `payload.data` from the event
 *    stream (Agent 1's ArtifactFeed already renders `a.data` when present).
 * 2. **Honesty flags.** Exposes `simulated` (any payload marked
 *    `simulated: true` — the backend demo simulator labels its events) and
 *    `dataGrounding` (the `run_started.data_grounding` note) so the UI can
 *    disclose demo content.
 *
 * Everything else is passed through untouched: the result is a superset of
 * `UseRunStreamResult`, so /runs/[id] can switch the import with zero other
 * changes. See components/live/README.md.
 */
import { useMemo } from "react";
import { useRunStream, type UseRunStreamResult } from "@/hooks/useRunStream";
import type { AgentForgeEvent, Artifact, ChartSpec, TableData } from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Payload data guards (mirror components/ArtifactFeed.tsx)            */
/* ------------------------------------------------------------------ */

function isChartSpec(data: unknown): data is ChartSpec {
  return (
    !!data &&
    typeof data === "object" &&
    "kind" in (data as Record<string, unknown>) &&
    "data" in (data as Record<string, unknown>) &&
    Array.isArray((data as Record<string, unknown>).data)
  );
}

function isTableData(data: unknown): data is TableData {
  return (
    !!data &&
    typeof data === "object" &&
    "columns" in (data as Record<string, unknown>) &&
    "rows" in (data as Record<string, unknown>)
  );
}

/** artifact_id -> structured payload data (ChartSpec / TableData). */
function payloadDataByArtifactId(events: AgentForgeEvent[]): Map<string, ChartSpec | TableData> {
  const byId = new Map<string, ChartSpec | TableData>();
  for (const e of events) {
    if (e.type !== "artifact_created") continue;
    const raw = (e.payload as unknown as Record<string, unknown>).data;
    if (isChartSpec(raw) || isTableData(raw)) {
      byId.set(e.payload.artifact_id, raw);
    }
  }
  return byId;
}

/** Attach payload data to artifacts that were parsed without it. */
function enrichArtifacts(
  artifacts: Artifact[],
  events: AgentForgeEvent[],
): Artifact[] {
  if (artifacts.length === 0) return artifacts;
  const payloadData = payloadDataByArtifactId(events);
  if (payloadData.size === 0) return artifacts;
  return artifacts.map((artifact) => {
    if (artifact.data) return artifact; // snapshot-provided data wins
    const data = payloadData.get(artifact.id);
    return data ? { ...artifact, data } : artifact;
  });
}

/* ------------------------------------------------------------------ */
/* Hook                                                                */
/* ------------------------------------------------------------------ */

export interface UseRunStreamV2Result extends UseRunStreamResult {
  /** Artifacts with structured `data` re-attached from artifact_created events. */
  artifacts: Artifact[];
  /** True when any event payload is labeled `simulated: true` (demo mode). */
  simulated: boolean;
  /** The run_started payload's data_grounding note, if the producer set one. */
  dataGrounding: string | null;
}

export function useRunStreamV2(runId: string): UseRunStreamV2Result {
  const base = useRunStream(runId);

  const artifacts = useMemo(
    () => enrichArtifacts(base.artifacts, base.events),
    [base.artifacts, base.events],
  );

  const simulated = useMemo(
    () =>
      base.events.some(
        (e) => (e.payload as Record<string, unknown>).simulated === true,
      ),
    [base.events],
  );

  const dataGrounding = useMemo(() => {
    for (const e of base.events) {
      if (e.type !== "run_started") continue;
      const note = (e.payload as Record<string, unknown>).data_grounding;
      if (typeof note === "string" && note) return note;
    }
    return null;
  }, [base.events]);

  return { ...base, artifacts, simulated, dataGrounding };
}

export default useRunStreamV2;
