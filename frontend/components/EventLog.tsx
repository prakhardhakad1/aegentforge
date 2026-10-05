"use client";
/**
 * EventLog — streaming, terminal-style feed of pinned event envelopes with
 * auto-scroll, agent filters, and humanized payload summaries.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { AGENT_META, agentLabel } from "@/lib/agents";
import type { AgentForgeEvent, AgentRole } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { Badge } from "./Badge";
import { EmptyState } from "./EmptyState";
import { cn } from "@/lib/utils";
import { AGENT_ROLES } from "@/lib/types";

/** Max rows kept in the DOM (older events collapse away). */
const MAX_RENDER = 250;

function typeTone(type: AgentForgeEvent["type"]): string {
  switch (type) {
    case "run_started":
      return "text-forge-600 dark:text-forge-400";
    case "plan_created":
      return "text-forge-600 dark:text-forge-400";
    case "run_finished":
      return "text-emerald-600 dark:text-emerald-400";
    case "run_failed":
      return "text-rose-600 dark:text-rose-400";
    case "artifact_created":
      return "text-violet-600 dark:text-violet-400";
    case "token_update":
      return "text-zinc-400 dark:text-zinc-500";
    case "tool_result":
      return "text-emerald-600/80 dark:text-emerald-400/80";
    default:
      return "text-zinc-600 dark:text-zinc-300";
  }
}

function humanize(e: AgentForgeEvent): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "run_started":
      return "Run started — team assembled.";
    case "plan_created": {
      const subtasks = Array.isArray(p.subtasks) ? p.subtasks : [];
      return `Plan drafted: ${subtasks.length} subtasks assigned across the team.`;
    }
    case "agent_started":
      return String(p.title ?? "started working");
    case "thought_summary":
      return String(p.summary ?? "");
    case "tool_call":
      return `Calling ${String(p.tool ?? "tool")}(${String(p.args_summary ?? "")})`;
    case "tool_result": {
      const ok = p.ok !== false;
      return `${ok ? "Done" : "Failed"}: ${String(p.tool ?? "tool")}${p.args_summary ? ` — ${String(p.args_summary)}` : ""}`;
    }
    case "artifact_created":
      return `Artifact ready: ${String(p.name ?? "artifact")} (${String(p.kind ?? "file")})`;
    case "step_completed":
      return "Step completed.";
    case "agent_finished":
      return "Handing off to the next specialist.";
    case "token_update": {
      const inTok = Number(p.input_tokens ?? 0);
      const outTok = Number(p.output_tokens ?? 0);
      return `+${(inTok + outTok).toLocaleString("en-US")} tokens this turn`;
    }
    case "run_finished":
      return "Run finished — report is ready.";
    case "run_failed":
      return `Run failed: ${String(p.error ?? "unknown error")}`;
    default:
      return JSON.stringify(p).slice(0, 140);
  }
}

export function EventLog({
  events,
  className,
  maxHeight = 560,
}: {
  events: AgentForgeEvent[];
  className?: string;
  maxHeight?: number;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [filter, setFilter] = useState<AgentRole | "all">("all");
  const [autoScroll, setAutoScroll] = useState(true);

  const presentRoles = useMemo(() => {
    const set = new Set<AgentRole>();
    for (const e of events) if (e.agent) set.add(e.agent);
    return AGENT_ROLES.filter((r) => set.has(r));
  }, [events]);

  const filtered = useMemo(
    () => (filter === "all" ? events : events.filter((e) => e.agent === filter)),
    [events, filter],
  );
  const visible = filtered.slice(-MAX_RENDER);
  const hiddenCount = filtered.length - visible.length;

  useEffect(() => {
    if (!autoScroll || !stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visible.length, autoScroll]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-zinc-200 px-4 py-2.5 dark:border-white/10">
        <button
          type="button"
          onClick={() => setFilter("all")}
          className={cn(
            "rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
            filter === "all"
              ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
              : "text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5",
          )}
        >
          All
        </button>
        {presentRoles.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setFilter(filter === r ? "all" : r)}
            className={cn(
              "rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
              filter === r
                ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                : "text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5",
            )}
          >
            {AGENT_META[r].label}
          </button>
        ))}
        <label className="ml-auto flex cursor-pointer select-none items-center gap-1.5 text-[11px] text-zinc-500 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="h-3 w-3 rounded border-zinc-300 accent-forge-500"
          />
          Follow
        </label>
      </div>

      {/* stream */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed"
        style={{ maxHeight }}
      >
        {filtered.length === 0 ? (
          <EmptyState
            className="py-10"
            title="No events yet"
            description="Agent activity streams here the moment the run starts."
            icon={
              <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
                <path
                  d="M6 5h12a1 1 0 0 1 1 1v9.6a1 1 0 0 1-.45.83L12 21l-6.55-4.57A1 1 0 0 1 5 15.6V6a1 1 0 0 1 1-1Zm0 3h12"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            }
          />
        ) : (
          <>
            {hiddenCount > 0 ? (
              <p className="mb-2 text-center text-[10px] text-zinc-400 dark:text-zinc-500">
                {hiddenCount.toLocaleString("en-US")} earlier events hidden
              </p>
            ) : null}
            <ul className="space-y-0.5">
              {visible.map((e) => (
                <li
                  key={e.seq}
                  className="group flex items-start gap-2 rounded px-1 py-0.5 transition-colors hover:bg-zinc-50 dark:hover:bg-white/5"
                >
                  <span className="w-16 shrink-0 tabular-nums text-zinc-400 dark:text-zinc-600">
                    {formatTime(e.ts)}
                  </span>
                  <span
                    className={cn(
                      "w-20 shrink-0 truncate font-sans text-[10px] font-semibold uppercase tracking-wide",
                      e.agent ? AGENT_META[e.agent].text : "text-zinc-400",
                    )}
                  >
                    {agentLabel(e.agent)}
                  </span>
                  <span className={cn("min-w-0 flex-1 break-words", typeTone(e.type))}>
                    {e.type === "thought_summary" ? (
                      <em className="text-zinc-500 dark:text-zinc-400">{humanize(e)}</em>
                    ) : (
                      humanize(e)
                    )}
                  </span>
                  <span className="hidden shrink-0 text-[10px] tabular-nums text-zinc-300 group-hover:inline dark:text-zinc-600">
                    #{e.seq}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {filtered.length > 0 ? (
        <div className="border-t border-zinc-200 px-4 py-2 dark:border-white/10">
          <Badge tone="zinc">
            <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-emerald-500" />
            {filtered.length.toLocaleString("en-US")} events
          </Badge>
        </div>
      ) : null}
    </div>
  );
}

export default EventLog;
