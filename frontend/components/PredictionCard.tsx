"use client";
import type { Prediction } from "@/lib/types";
import { cn } from "@/lib/utils";

function confidenceColor(c: number): string {
  if (c >= 0.75) return "bg-emerald-500";
  if (c >= 0.5) return "bg-amber-500";
  return "bg-rose-400";
}

function confidenceLabel(c: number): string {
  if (c >= 0.75) return "High confidence";
  if (c >= 0.5) return "Medium confidence";
  return "Low confidence";
}

export function PredictionCard({ prediction, className }: { prediction: Prediction; className?: string }) {
  const pct = Math.round(Math.min(1, Math.max(0, prediction.confidence)) * 100);
  return (
    <article
      className={cn(
        "flex h-full flex-col rounded-2xl border border-zinc-200 bg-white p-5 shadow-card dark:border-white/10 dark:bg-zinc-900/60",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-700 ring-1 ring-inset ring-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/20">
          Prediction
        </span>
        <span
          className={cn(
            "text-sm font-bold tabular-nums",
            pct >= 75 ? "text-emerald-600 dark:text-emerald-400" : pct >= 50 ? "text-amber-600 dark:text-amber-400" : "text-rose-500 dark:text-rose-400",
          )}
        >
          {pct}%
        </span>
      </div>
      <p className="mt-2.5 flex-1 text-sm font-medium leading-relaxed text-zinc-900 dark:text-zinc-100">
        {prediction.claim}
      </p>
      <div className="mt-3">
        <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-white/10">
          <div
            className={cn("h-full rounded-full transition-all duration-700", confidenceColor(prediction.confidence))}
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-1 text-[10px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
          {confidenceLabel(prediction.confidence)}
        </p>
      </div>
      {prediction.basis ? (
        <p className="mt-2.5 border-t border-zinc-100 pt-2.5 text-xs leading-relaxed text-zinc-500 dark:border-white/5 dark:text-zinc-400">
          <span className="font-semibold text-zinc-600 dark:text-zinc-300">Basis: </span>
          {prediction.basis}
        </p>
      ) : null}
    </article>
  );
}

export default PredictionCard;
