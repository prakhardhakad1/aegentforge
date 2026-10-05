"use client";
import type { Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

const EFFORT: Record<Recommendation["effort"], { label: string; className: string }> = {
  S: { label: "Small", className: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20" },
  M: { label: "Medium", className: "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/20" },
  L: { label: "Large", className: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20" },
};

export function RecommendationTable({
  recommendations,
  className,
}: {
  recommendations: Recommendation[];
  className?: string;
}) {
  const sorted = [...recommendations].sort((a, b) => a.priority - b.priority);
  if (sorted.length === 0) {
    return (
      <p className={cn("px-4 py-8 text-center text-sm text-zinc-500 dark:text-zinc-400", className)}>
        No recommendations in this report.
      </p>
    );
  }
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-200 dark:border-white/10">
            <th scope="col" className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
              Priority
            </th>
            <th scope="col" className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
              Recommendation
            </th>
            <th scope="col" className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
              Action
            </th>
            <th scope="col" className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
              Expected impact
            </th>
            <th scope="col" className="px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
              Effort
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const effort = EFFORT[r.effort] ?? EFFORT.M;
            return (
              <tr key={r.priority} className="border-b border-zinc-100 align-top last:border-0 dark:border-white/5">
                <td className="px-4 py-4">
                  <span
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-lg text-xs font-bold",
                      r.priority <= 3
                        ? "bg-gradient-to-br from-forge-400 to-forge-600 text-white shadow-sm"
                        : "bg-zinc-100 text-zinc-500 dark:bg-white/10 dark:text-zinc-400",
                    )}
                  >
                    {r.priority}
                  </span>
                </td>
                <td className="px-4 py-4 font-medium text-zinc-900 dark:text-zinc-100">{r.title}</td>
                <td className="max-w-xs px-4 py-4 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{r.action}</td>
                <td className="max-w-xs px-4 py-4 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{r.expected_impact}</td>
                <td className="px-4 py-4">
                  <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", effort.className)}>
                    {effort.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default RecommendationTable;
