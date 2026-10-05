"use client";
/**
 * Timeline — the plan (subtask DAG) as a vertical timeline with per-agent
 * avatars, live status icons and connecting rails.
 */
import { AGENT_META } from "@/lib/agents";
import type { AgentRole, Subtask } from "@/lib/types";
import { AgentAvatar } from "./AgentAvatar";
import { Spinner } from "./Spinner";
import { cn } from "@/lib/utils";

function statusIcon(status: string): React.ReactNode {
  if (status === "done")
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-500/20">
        <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3 text-emerald-600 dark:text-emerald-400" aria-hidden>
          <path d="m5 13 4 4L19 7" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  if (status === "running") return <Spinner size="xs" />;
  if (status === "failed")
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 dark:bg-rose-500/20">
        <svg viewBox="0 0 24 24" fill="none" className="h-3 w-3 text-rose-600 dark:text-rose-400" aria-hidden>
          <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      </span>
    );
  return <span aria-hidden className="h-2.5 w-2.5 rounded-full border-2 border-dashed border-zinc-300 dark:border-zinc-600" />;
}

export function Timeline({
  plan,
  className,
}: {
  plan: Subtask[];
  className?: string;
}) {
  if (plan.length === 0) {
    return (
      <div className={cn("px-5 py-8 text-center", className)}>
        <Spinner size="sm" label="Waiting for the planner to draft the plan…" />
      </div>
    );
  }
  return (
    <ol className={cn("relative space-y-1 px-5 py-4", className)}>
      {plan.map((task, i) => {
        const meta = AGENT_META[task.agent as AgentRole];
        const isLast = i === plan.length - 1;
        const running = task.status === "running";
        return (
          <li key={task.id} className="relative flex gap-3 pb-4 last:pb-0">
            {!isLast ? (
              <span
                aria-hidden
                className={cn(
                  "absolute left-[17px] top-9 h-[calc(100%-20px)] w-0.5 rounded",
                  task.status === "done" ? "bg-emerald-300 dark:bg-emerald-500/40" : "bg-zinc-200 dark:bg-white/10",
                )}
              />
            ) : null}
            <div className="relative z-10 mt-0.5">
              <AgentAvatar role={task.agent as AgentRole} size="sm" active={running} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p
                  className={cn(
                    "min-w-0 flex-1 text-sm leading-snug",
                    task.status === "done"
                      ? "text-zinc-500 line-through decoration-zinc-300 dark:text-zinc-500"
                      : "font-medium text-zinc-900 dark:text-zinc-100",
                  )}
                >
                  {task.title}
                </p>
                <span className="shrink-0">{statusIcon(task.status)}</span>
              </div>
              <p className={cn("mt-0.5 text-xs", meta.text)}>
                {meta.label}
                {task.depends_on.length > 0 ? (
                  <span className="ml-2 text-zinc-400 dark:text-zinc-500">
                    after {task.depends_on.length} {task.depends_on.length === 1 ? "step" : "steps"}
                  </span>
                ) : null}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export default Timeline;
