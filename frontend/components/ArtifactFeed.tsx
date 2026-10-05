"use client";
/**
 * ArtifactFeed — artifacts as they land, with rich inline previews for chart
 * and table artifacts when structured data is present (demo engine includes
 * it; the live backend may too — otherwise metadata only).
 */
import { useMemo } from "react";
import type { Artifact, ChartSpec, TableData } from "@/lib/types";
import { ChartBlock } from "./ChartBlock";
import { EmptyState } from "./EmptyState";
import { cn } from "@/lib/utils";

const KIND_META: Record<Artifact["kind"], { label: string; icon: React.ReactNode }> = {
  chart: {
    label: "Chart",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <path d="M4 20h16M7 16v-5m5 5V8m5 8v-3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
  table: {
    label: "Table",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <rect x="3.5" y="5" width="17" height="14" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
        <path d="M3.5 10h17M9.5 10v9" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    ),
  },
  text: {
    label: "Note",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <path
          d="M7 3.5h7L19 8.5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1Zm7 0v5h5M9 13h6m-6 4h4"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  prediction: {
    label: "Prediction",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="12" cy="12" r="4.5" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="12" cy="12" r="1" fill="currentColor" />
      </svg>
    ),
  },
  recommendation: {
    label: "Recommendation",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <path d="M4 7h16M4 12h10M4 17h7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
  report_markdown: {
    label: "Report (MD)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <path
          d="M7 3.5h7L19 8.5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1Zm7 0v5h5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  report_pdf: {
    label: "Report (PDF)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <path
          d="M7 3.5h7L19 8.5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-16a1 1 0 0 1 1-1Zm7 0v5h5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  file: {
    label: "File",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
        <path
          d="m20.4 12.6-7.8 7.8a5 5 0 0 1-7-7l8-8a3.4 3.4 0 0 1 4.8 4.8l-8 8a1.8 1.8 0 0 1-2.5-2.5l7.2-7.2"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
};

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

export function ArtifactFeed({
  artifacts,
  className,
}: {
  artifacts: Artifact[];
  className?: string;
}) {
  // Newest first.
  const ordered = useMemo(() => [...artifacts].reverse(), [artifacts]);

  if (ordered.length === 0) {
    return (
      <EmptyState
        className={className}
        title="No artifacts yet"
        description="Charts, tables and findings appear here as agents produce them."
        icon={
          <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
            <path
              d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        }
      />
    );
  }

  return (
    <ul className={cn("space-y-3 px-4 py-4", className)}>
      {ordered.map((a) => {
        const meta = KIND_META[a.kind] ?? KIND_META.file;
        return (
          <li
            key={a.id}
            className="animate-fade-up rounded-xl border border-zinc-200 bg-zinc-50/60 p-3.5 dark:border-white/10 dark:bg-white/[0.03]"
          >
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 text-zinc-400 dark:text-zinc-500">{meta.icon}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{a.name}</p>
                  <span className="shrink-0 rounded bg-zinc-200/70 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-600 dark:bg-white/10 dark:text-zinc-400">
                    {meta.label}
                  </span>
                </div>
                {a.summary ? (
                  <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
                    {a.summary}
                  </p>
                ) : null}
              </div>
            </div>
            {isChartSpec(a.data) ? (
              <div className="mt-3">
                <ChartBlock spec={a.data} height={180} />
              </div>
            ) : null}
            {isTableData(a.data) && a.data.rows.length > 0 ? (
              <div className="mt-3 overflow-x-auto rounded-lg border border-zinc-200 dark:border-white/10">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className="bg-zinc-100 dark:bg-white/5">
                      {a.data.columns.map((c) => (
                        <th key={c} className="whitespace-nowrap px-2 py-1.5 font-semibold text-zinc-600 dark:text-zinc-300">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {a.data.rows.slice(0, 4).map((row, ri) => (
                      <tr key={ri} className="border-t border-zinc-100 dark:border-white/5">
                        {a.data && isTableData(a.data)
                          ? (a.data as TableData).columns.map((c, ci) => (
                              <td key={c} className="whitespace-nowrap px-2 py-1.5 tabular-nums text-zinc-600 dark:text-zinc-400">
                                {String(row[ci] ?? "")}
                              </td>
                            ))
                          : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export default ArtifactFeed;
