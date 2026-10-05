"use client";
/**
 * CostBreakdown — post-run per-agent token/cost table (Agent 7, additive).
 *
 * Complements components/TokenMeter.tsx (live bars during the run): once
 * agents have produced usage, this renders the auditable breakdown the
 * judging brief asks for — input vs output split, totals, cost and each
 * agent's share of the run cost, colored by role.
 *
 * Pure presentational: takes the same `TokenUsage` shape the run snapshot
 * and token_update events produce, so /runs/[id] can drop it under the
 * TokenMeter card (see components/live/README.md).
 */
import { AGENT_META, agentLabel } from "@/lib/agents";
import type { AgentRole, TokenUsage } from "@/lib/types";
import { cn, formatNumber, formatUsd } from "@/lib/utils";

export interface CostBreakdownProps {
  tokenUsage: TokenUsage;
  className?: string;
}

interface Row {
  role: AgentRole;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  costUsd: number;
  share: number; // 0..1 of run cost
}

function buildRows(tokenUsage: TokenUsage): Row[] {
  const totalCost =
    tokenUsage.totals?.cost_usd ?? 0;
  const rows: Row[] = [];
  for (const [roleRaw, usage] of Object.entries(tokenUsage.per_agent ?? {})) {
    if (!usage) continue;
    const { input_tokens, output_tokens, cost_usd } = usage;
    if (input_tokens <= 0 && output_tokens <= 0 && cost_usd <= 0) continue;
    rows.push({
      role: roleRaw as AgentRole,
      inputTokens: input_tokens,
      outputTokens: output_tokens,
      totalTokens: input_tokens + output_tokens,
      costUsd: cost_usd,
      share: totalCost > 0 ? cost_usd / totalCost : 0,
    });
  }
  rows.sort((a, b) => b.costUsd - a.costUsd || a.role.localeCompare(b.role));
  return rows;
}

export function CostBreakdown({ tokenUsage, className }: CostBreakdownProps) {
  const rows = buildRows(tokenUsage);
  if (rows.length === 0) return null;
  const totals = tokenUsage.totals ?? {
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: 0,
  };

  return (
    <div className={cn("px-4 py-4", className)}>
      <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
        Cost breakdown by agent
      </p>
      <div className="mt-2 overflow-x-auto rounded-xl border border-zinc-200 dark:border-white/10">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="bg-zinc-50 dark:bg-white/[0.04]">
              <th className="px-3 py-2 font-semibold text-zinc-600 dark:text-zinc-300">Agent</th>
              <th className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-600 dark:text-zinc-300">Input</th>
              <th className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-600 dark:text-zinc-300">Output</th>
              <th className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-600 dark:text-zinc-300">Tokens</th>
              <th className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-600 dark:text-zinc-300">Cost</th>
              <th className="px-3 py-2 font-semibold text-zinc-600 dark:text-zinc-300">Share</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const meta = AGENT_META[row.role] ?? AGENT_META.planner;
              return (
                <tr
                  key={row.role}
                  className="border-t border-zinc-100 dark:border-white/5"
                >
                  <td className={cn("whitespace-nowrap px-3 py-2 font-medium", meta.text)}>
                    {agentLabel(row.role)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-600 dark:text-zinc-400">
                    {formatNumber(row.inputTokens)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-600 dark:text-zinc-400">
                    {formatNumber(row.outputTokens)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-900 dark:text-zinc-100">
                    {formatNumber(row.totalTokens)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-900 dark:text-zinc-100">
                    {formatUsd(row.costUsd)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-100 dark:bg-white/10">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.max(2, Math.round(row.share * 100))}%`,
                            background: meta.hex,
                          }}
                        />
                      </div>
                      <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
                        {Math.round(row.share * 100)}%
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-zinc-200 bg-zinc-50 dark:border-white/10 dark:bg-white/[0.04]">
              <td className="px-3 py-2 font-semibold text-zinc-900 dark:text-zinc-100">Total</td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                {formatNumber(totals.input_tokens)}
              </td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                {formatNumber(totals.output_tokens)}
              </td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                {formatNumber(totals.input_tokens + totals.output_tokens)}
              </td>
              <td className="px-3 py-2 text-right font-semibold tabular-nums text-forge-600 dark:text-forge-400">
                {formatUsd(totals.cost_usd)}
              </td>
              <td className="px-3 py-2 text-zinc-500 dark:text-zinc-400">100%</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

export default CostBreakdown;
