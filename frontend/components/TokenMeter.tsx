"use client";
/**
 * TokenMeter — per-agent token/cost bars plus run totals. Updates live from
 * token_update events.
 */
import { AGENT_META, agentLabel } from "@/lib/agents";
import type { AgentRole, TokenUsage } from "@/lib/types";
import { formatNumber, formatUsd } from "@/lib/utils";
import { cn } from "@/lib/utils";

export function TokenMeter({
  tokenUsage,
  className,
}: {
  tokenUsage: TokenUsage;
  className?: string;
}) {
  const entries = (Object.entries(tokenUsage.per_agent) as Array<[AgentRole, { input_tokens: number; output_tokens: number; cost_usd: number }]>)
    .filter(([, v]) => v && (v.input_tokens > 0 || v.output_tokens > 0 || v.cost_usd > 0));
  const maxCost = Math.max(0.0001, ...entries.map(([, v]) => v.cost_usd));
  const totals = tokenUsage.totals ?? { input_tokens: 0, output_tokens: 0, cost_usd: 0 };

  return (
    <div className={cn("px-4 py-4", className)}>
      <div className="grid grid-cols-3 gap-2 rounded-xl bg-zinc-50 p-3 dark:bg-white/[0.04]">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Input</p>
          <p className="mt-0.5 text-sm font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
            {formatNumber(totals.input_tokens)}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Output</p>
          <p className="mt-0.5 text-sm font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
            {formatNumber(totals.output_tokens)}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Est. cost</p>
          <p className="mt-0.5 text-sm font-semibold tabular-nums text-forge-600 dark:text-forge-400">
            {formatUsd(totals.cost_usd)}
          </p>
        </div>
      </div>

      {entries.length === 0 ? (
        <p className="mt-3 text-center text-xs text-zinc-400 dark:text-zinc-500">
          Token usage appears as agents work.
        </p>
      ) : (
        <ul className="mt-3 space-y-2.5">
          {entries.map(([role, usage]) => {
            const meta = AGENT_META[role] ?? AGENT_META.planner;
            const pct = Math.max(3, Math.round((usage.cost_usd / maxCost) * 100));
            return (
              <li key={role}>
                <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
                  <span className={cn("font-medium", meta.text)}>{agentLabel(role)}</span>
                  <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
                    {formatNumber(usage.input_tokens + usage.output_tokens)} tok · {formatUsd(usage.cost_usd)}
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-white/10">
                  <div
                    className="h-full rounded-full transition-all duration-700 ease-out"
                    style={{ width: `${pct}%`, background: meta.hex }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default TokenMeter;
