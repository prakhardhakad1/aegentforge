"use client";
/**
 * /runs/[id] — live run view: agent timeline, streaming event log, artifact
 * feed and token/cost meter. Consumes the pinned WS endpoint with polling
 * fallback via hooks/useRunStream.ts.
 */
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { humanizeTemplateId, truncate } from "@/lib/utils";
import type { ConnectionState } from "@/hooks/useRunStream";
import { useRunStream } from "@/hooks/useRunStream";
import { Button } from "@/components/Button";
import { Card, CardHeader } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { EventLog } from "@/components/EventLog";
import { ArtifactFeed } from "@/components/ArtifactFeed";
import { Skeleton, SkeletonCard } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";
import { TokenMeter } from "@/components/TokenMeter";
import { useToast } from "@/components/Toaster";

const CONNECTION_META: Record<ConnectionState, { label: string; className: string; dot: string }> = {
  connecting: { label: "Connecting…", className: "text-zinc-500 dark:text-zinc-400", dot: "bg-zinc-400 animate-pulse-dot" },
  live: { label: "Live · WebSocket", className: "text-emerald-600 dark:text-emerald-400", dot: "bg-emerald-500" },
  polling: { label: "Live · polling fallback", className: "text-sky-600 dark:text-sky-400", dot: "bg-sky-500 animate-pulse-dot" },
  demo: { label: "Live · demo simulation", className: "text-amber-600 dark:text-amber-400", dot: "bg-amber-500 animate-pulse-dot" },
  closed: { label: "Stream closed", className: "text-zinc-400 dark:text-zinc-500", dot: "bg-zinc-400" },
  error: { label: "Stream error", className: "text-rose-600 dark:text-rose-400", dot: "bg-rose-500" },
};

function N8nIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5" aria-hidden>
      <circle cx="5" cy="12" r="2.2" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="12" cy="6" r="2.2" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="12" cy="18" r="2.2" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="19" cy="12" r="2.2" stroke="currentColor" strokeWidth="1.7" />
      <path d="M7 11l3-3.4M7 13l3 3.4m4-8.4 3 3.4m-3 1.6 3 3.4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export default function RunPage() {
  const params = useParams<{ id: string }>();
  const runId = params?.id ?? "";
  const stream = useRunStream(runId);
  const toastApi = useToast();
  const [exporting, setExporting] = useState(false);

  const conn = CONNECTION_META[stream.connection];

  const exportN8n = async () => {
    setExporting(true);
    try {
      const wf = await api.exportN8n(runId);
      const blob = new Blob([JSON.stringify(wf, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `agentforge-n8n-${runId}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 2000);
      toastApi.success("n8n workflow exported", "Import the JSON file into n8n.");
    } catch (err) {
      toastApi.error("n8n export failed", err instanceof Error ? err.message : "Unknown error");
    } finally {
      setExporting(false);
    }
  };

  /* ---- loading ---- */
  if (!stream.run && !stream.error) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="mt-2 h-4 w-40" />
        <div className="mt-6 grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)_330px]">
          <SkeletonCard lines={6} />
          <SkeletonCard lines={12} />
          <div className="space-y-4">
            <SkeletonCard lines={3} />
            <SkeletonCard lines={4} />
          </div>
        </div>
      </div>
    );
  }

  /* ---- error ---- */
  if (!stream.run && stream.error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
        <ErrorState title="Could not open this run" message={stream.error} onRetry={stream.retry} />
        <div className="mt-6 text-center">
          <Button href="/new" variant="ghost" size="sm">
            Start a new mission instead
          </Button>
        </div>
      </div>
    );
  }

  const run = stream.run;
  const mission = stream.mission;
  const reportReady = stream.reportReady || stream.status === "succeeded" || !!stream.report;

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={stream.status} />
            <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${conn.className}`}>
              <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${conn.dot}`} />
              {conn.label}
            </span>
            <span className="text-xs text-zinc-400 dark:text-zinc-500">
              {humanizeTemplateId(mission?.template_id)} · {run?.id}
            </span>
          </div>
          <h1 className="mt-2 max-w-3xl text-lg font-bold leading-snug text-zinc-900 sm:text-xl dark:text-zinc-50">
            {mission?.goal ?? "Run"}
          </h1>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={exportN8n} loading={exporting}>
            <N8nIcon />
            Export n8n
          </Button>
          {reportReady ? (
            <Button href={`/runs/${runId}/report`} size="sm">
              View report
            </Button>
          ) : null}
        </div>
      </div>

      {stream.error && stream.run ? (
        <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300">
          {stream.error}
        </div>
      ) : null}

      {/* three-column layout */}
      <div className="mt-6 grid items-start gap-4 lg:grid-cols-[300px_minmax(0,1fr)_330px]">
        {/* plan timeline */}
        <Card>
          <CardHeader
            title="Agent timeline"
            subtitle={stream.plan.length ? `${stream.plan.length} subtasks` : "waiting for the planner"}
            icon={
              <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
                <path d="M5 6h14M5 12h9M5 18h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            }
          />
          <Timeline plan={stream.plan} />
        </Card>

        {/* event stream */}
        <Card className="overflow-hidden">
          <CardHeader
            title="Live event stream"
            subtitle={truncate(mission?.goal ?? "", 70)}
            icon={
              <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
                <path d="M4 7h12M4 12h16M4 17h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            }
            action={
              stream.status === "running" ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-600 dark:bg-sky-500/10 dark:text-sky-400">
                  <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-sky-500" />
                  streaming
                </span>
              ) : undefined
            }
          />
          <EventLog events={stream.events} maxHeight={620} />
        </Card>

        {/* right rail */}
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Tokens & cost"
              icon={
                <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
                  <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.7" />
                  <path d="M12 7.5v9M9.5 9.8c0-.9 1.1-1.6 2.5-1.6s2.5.7 2.5 1.6c0 2.4-5 1.6-5 4 0 .9 1.1 1.6 2.5 1.6s2.5-.7 2.5-1.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              }
            />
            <TokenMeter tokenUsage={stream.tokenUsage} />
          </Card>
          <Card>
            <CardHeader
              title="Artifacts"
              subtitle={`${stream.artifacts.length} produced`}
              icon={
                <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
                  <path d="M4 7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7Zm4 4h8m-8 4h5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                </svg>
              }
            />
            <div className="max-h-[520px] overflow-y-auto">
              <ArtifactFeed artifacts={stream.artifacts} />
            </div>
          </Card>
        </div>
      </div>

      {/* bottom CTA when finished */}
      {reportReady ? (
        <div className="mt-8 flex flex-col items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-6 text-center dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]">
          <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
            The critic signed off — your report is ready.
          </p>
          <div className="flex gap-2">
            <Button href={`/runs/${runId}/report`} size="md">
              Open the report
            </Button>
            <Button variant="secondary" size="md" onClick={exportN8n} loading={exporting}>
              Export as n8n workflow
            </Button>
          </div>
        </div>
      ) : stream.status !== "failed" ? (
        <EmptyState
          className="mt-8"
          title="Report pending"
          description="The report unlocks once every specialist and the critic have finished."
        />
      ) : null}
    </div>
  );
}
