"use client";
/**
 * /runs/[id]/report — structured report view. Polls GET /api/runs/{id} until
 * the report lands (or the run fails), then renders ReportView with
 * Markdown / PDF download buttons (client-rendered in demo mode).
 */
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { RunSnapshot } from "@/lib/types";
import { useRunStream } from "@/hooks/useRunStream";
import { Button } from "@/components/Button";
import { ErrorState } from "@/components/ErrorState";
import { ReportView } from "@/components/ReportView";
import { Skeleton, SkeletonCard } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { useToast } from "@/components/Toaster";
import { Spinner } from "@/components/Spinner";

type DownloadFormat = "markdown" | "pdf";

export default function RunReportPage() {
  const params = useParams<{ id: string }>();
  const runId = params?.id ?? "";
  const toastApi = useToast();

  // Live-run state powers the "generating…" progress panel while the report
  // is being produced.
  const stream = useRunStream(runId);

  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<DownloadFormat | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const attemptsRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const snap = await api.getRun(runId);
        if (cancelled) return;
        setSnapshot(snap);
        setPollError(null);
        attemptsRef.current = 0;
      } catch (err) {
        if (cancelled) return;
        attemptsRef.current += 1;
        if (attemptsRef.current >= 3) {
          setPollError(err instanceof Error ? err.message : "Could not load the report.");
        }
      }
    };
    void poll();
    const timer = setInterval(() => {
      const terminal = snapshot?.run.status;
      const done = terminal === "succeeded" || terminal === "failed" || terminal === "partial";
      if (!snapshot?.report && !done) void poll();
    }, 2500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, retryNonce, snapshot?.report, snapshot?.run.status]);

  const handleDownload = useCallback(
    async (format: DownloadFormat) => {
      setDownloading(format);
      try {
        await api.downloadReport(runId, format, snapshot?.report ?? null);
        toastApi.success(format === "pdf" ? "PDF downloaded" : "Markdown downloaded");
      } catch (err) {
        toastApi.error("Download failed", err instanceof Error ? err.message : "Unknown error");
      } finally {
        setDownloading(null);
      }
    },
    [runId, snapshot?.report, toastApi],
  );

  /* ---- loading shell ---- */
  if (!snapshot && !pollError) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 lg:px-8">
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="mt-3 h-4 w-96" />
        <div className="mt-8 space-y-4">
          <SkeletonCard lines={4} />
          <div className="grid gap-4 md:grid-cols-2">
            <SkeletonCard lines={5} />
            <SkeletonCard lines={5} />
          </div>
        </div>
      </div>
    );
  }

  /* ---- poll error ---- */
  if (!snapshot && pollError) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
        <ErrorState
          title="Could not load the report"
          message={pollError}
          onRetry={() => {
            setPollError(null);
            attemptsRef.current = 0;
            setRetryNonce((n) => n + 1);
          }}
        />
        <div className="mt-6 text-center">
          <Button href={`/runs/${runId}`} variant="ghost" size="sm">
            Back to the live run
          </Button>
        </div>
      </div>
    );
  }

  const report = snapshot?.report ?? null;
  const status = snapshot?.run.status ?? "queued";

  /* ---- report ready ---- */
  if (report) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <StatusBadge status={status} />
          <Button href={`/runs/${runId}`} variant="ghost" size="sm">
            ← Back to the live run
          </Button>
        </div>
        <ReportView report={report} onDownload={handleDownload} downloading={downloading} />
      </div>
    );
  }

  /* ---- generating / failed ---- */
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      {status === "failed" ? (
        <ErrorState
          title="The run failed before the report was produced"
          message={stream.error ?? "Check the live run view for the failing stage."}
        />
      ) : (
        <div className="rounded-2xl border border-zinc-200 bg-white p-8 text-center shadow-card dark:border-white/10 dark:bg-zinc-900/60">
          <div className="mx-auto w-fit">
            <Spinner size="lg" />
          </div>
          <h1 className="mt-4 text-lg font-bold text-zinc-900 dark:text-zinc-50">
            The team is still writing your report
          </h1>
          <p className="mx-auto mt-2 max-w-md text-sm text-zinc-500 dark:text-zinc-400">
            {stream.plan.length > 0
              ? `${stream.plan.filter((s) => s.status === "done").length} of ${stream.plan.length} subtasks done — this page unlocks the moment the critic signs off.`
              : "The planner is assembling the team. This page unlocks the moment the critic signs off."}
          </p>
          <div className="mx-auto mt-5 h-1.5 max-w-sm overflow-hidden rounded-full bg-zinc-100 dark:bg-white/10">
            <div
              className="h-full rounded-full bg-gradient-to-r from-forge-500 to-amber-400 transition-all duration-700"
              style={{
                width:
                  stream.plan.length > 0
                    ? `${Math.round((stream.plan.filter((s) => s.status === "done").length / stream.plan.length) * 100)}%`
                    : "12%",
              }}
            />
          </div>
          <div className="mt-6">
            <Button href={`/runs/${runId}`} variant="secondary" size="sm">
              Watch the run live
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
