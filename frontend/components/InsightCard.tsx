"use client";
import type { Insight, InsightStrength } from "@/lib/types";
import { cn } from "@/lib/utils";

const STRENGTH: Record<InsightStrength, { label: string; tone: string; dot: string }> = {
  high: {
    label: "Strong",
    tone: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20",
    dot: "bg-emerald-500",
  },
  medium: {
    label: "Medium",
    tone: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/20",
    dot: "bg-amber-500",
  },
  low: {
    label: "Weak",
    tone: "bg-zinc-100 text-zinc-600 ring-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:ring-white/10",
    dot: "bg-zinc-400",
  },
};

export function InsightCard({ insight, rank, className }: { insight: Insight; rank?: number; className?: string }) {
  const s = STRENGTH[insight.strength] ?? STRENGTH.low;
  return (
    <article
      className={cn(
        "flex h-full flex-col rounded-2xl border border-zinc-200 bg-white p-5 shadow-card dark:border-white/10 dark:bg-zinc-900/60",
        className,
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        {rank !== undefined ? (
          <span
            aria-label={`Ranked ${rank}`}
            className={cn(
              "flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-xs font-bold",
              rank <= 2
                ? "bg-gradient-to-br from-forge-400 to-forge-600 text-white"
                : "bg-zinc-100 text-zinc-500 dark:bg-white/10 dark:text-zinc-400",
            )}
          >
            {rank}
          </span>
        ) : null}
        <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", s.tone)}>
          <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
          {s.label} evidence
        </span>
      </div>
      <h3 className="text-sm font-semibold leading-snug text-zinc-900 dark:text-zinc-100">{insight.title}</h3>
      <p className="mt-2 flex-1 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{insight.detail}</p>
      {insight.evidence?.length ? (
        <div className="mt-3 border-t border-zinc-100 pt-3 dark:border-white/5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Evidence</p>
          <ul className="mt-1.5 space-y-1">
            {insight.evidence.map((e, i) => (
              <li key={i} className="flex gap-2 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
                <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-zinc-300 dark:bg-zinc-600" />
                <span className="min-w-0">{e}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

export default InsightCard;
