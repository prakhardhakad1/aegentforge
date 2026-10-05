"use client";
/**
 * HeroA (RECOMMENDED) — split hero: copy + CTAs on the left, a stylized
 * "live run console" mock on the right showing the agent pipeline working.
 * The console visual doubles as product demo: it shows the planner →
 * workers → critic loop judges reward.
 */
import Link from "next/link";
import { AGENT_META } from "@/lib/agents";
import { AGENT_ROLES } from "@/lib/types";
import { AgentAvatar } from "@/components/AgentAvatar";

const CONSOLE_LINES: Array<{ agent: string | null; text: string; dim?: boolean }> = [
  { agent: "planner", text: "Plan drafted — 5 subtasks assigned across the team." },
  { agent: "researcher", text: "web_search(benchmarks, industry norms) — 6 sources found" },
  { agent: "analyst", text: "python_sandbox(q3_subscribers.csv) — segment stats ready" },
  { agent: "analyst", text: "make_chart(trend + segment) — 2 charts attached" },
  { agent: "forecaster", text: "scenario_model() — Q4 churn: 8.5–9.8% status-quo", dim: true },
  { agent: "critic", text: "Downgraded 1 claim to medium strength. Report ready." },
];

export function HeroA() {
  return (
    <section className="relative overflow-hidden">
      {/* backdrop glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-forge-500/10 blur-3xl dark:bg-forge-500/15"
      />
      <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 pb-16 pt-14 sm:px-6 lg:grid-cols-2 lg:gap-10 lg:pb-24 lg:pt-20 lg:px-8">
        {/* copy */}
        <div className="animate-fade-up">
          <p className="inline-flex items-center gap-2 rounded-full border border-forge-200 bg-forge-50 px-3 py-1 text-xs font-semibold text-forge-700 dark:border-forge-500/30 dark:bg-forge-500/10 dark:text-forge-300">
            <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-forge-500" />
            ForgeHacks Online 2026 — AI + Business track
          </p>
          <h1 className="mt-5 text-4xl font-extrabold leading-[1.08] tracking-tight text-zinc-900 sm:text-5xl lg:text-[3.4rem] dark:text-zinc-50">
            Hire an AI team with{" "}
            <span className="bg-gradient-to-r from-forge-500 via-orange-500 to-amber-400 bg-clip-text text-transparent">
              one sentence
            </span>
            .
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-zinc-600 sm:text-lg dark:text-zinc-400">
            Describe a business goal. AgentForge spawns a planner and a crew of specialists —
            researcher, analyst, forecaster, critic — who work it live and hand you a
            decision-ready report: insights, charts, predictions, ranked recommendations.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link
              href="/new"
              className="inline-flex h-12 items-center rounded-xl bg-gradient-to-b from-forge-500 to-forge-600 px-6 text-base font-semibold text-white shadow-glow transition-all hover:from-forge-400 hover:to-forge-500"
            >
              Start a mission — free
            </Link>
            <Link
              href="/templates"
              className="inline-flex h-12 items-center rounded-xl border border-zinc-300 bg-white px-6 text-base font-medium text-zinc-800 transition-colors hover:bg-zinc-50 dark:border-white/15 dark:bg-white/5 dark:text-zinc-100 dark:hover:bg-white/10"
            >
              Browse AI teams
            </Link>
          </div>
          <div className="mt-8 flex items-center gap-3">
            <div className="flex -space-x-2">
              {AGENT_ROLES.map((r) => (
                <AgentAvatar key={r} role={r} size="sm" className="ring-2 ring-white dark:ring-zinc-950" />
              ))}
            </div>
            <p className="text-xs leading-snug text-zinc-500 dark:text-zinc-400">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">5 specialists per run.</span>
              <br />
              Planner → workers → critic loop, streamed live.
            </p>
          </div>
        </div>

        {/* console mock */}
        <div className="animate-fade-up [animation-delay:150ms]" aria-hidden>
          <div className="relative mx-auto max-w-lg">
            <div className="absolute -inset-3 rounded-3xl bg-gradient-to-br from-forge-500/15 via-transparent to-sky-500/10 blur-xl" />
            <div className="relative rounded-2xl border border-zinc-200 bg-white shadow-xl dark:border-white/10 dark:bg-zinc-900">
              <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-3 dark:border-white/5">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                <span className="ml-2 font-mono text-[11px] text-zinc-400 dark:text-zinc-500">
                  live run — churn mission
                </span>
                <span className="ml-auto rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400">
                  report ready
                </span>
              </div>
              <div className="space-y-2.5 px-4 py-4 font-mono text-[11px] leading-relaxed">
                {CONSOLE_LINES.map((line, i) => (
                  <p
                    key={i}
                    className="animate-fade-in opacity-0"
                    style={{ animationDelay: `${250 + i * 350}ms`, animationFillMode: "both" }}
                  >
                    <span className={line.agent ? AGENT_META[line.agent as keyof typeof AGENT_META].text : "text-zinc-400"}>
                      [{line.agent ?? "system"}]
                    </span>{" "}
                    <span className={line.dim ? "text-zinc-400 dark:text-zinc-500" : "text-zinc-700 dark:text-zinc-300"}>
                      {line.text}
                    </span>
                  </p>
                ))}
                <p className="pt-1 text-zinc-300 dark:text-zinc-600">
                  <span className="inline-block h-3 w-1.5 animate-blink bg-forge-500 align-middle" />
                </p>
              </div>
            </div>
            {/* floating token chip */}
            <div className="absolute -bottom-4 -left-4 hidden rounded-xl border border-zinc-200 bg-white px-3 py-2 shadow-lg dark:border-white/10 dark:bg-zinc-900 sm:block">
              <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">Run cost</p>
              <p className="text-sm font-bold tabular-nums text-forge-600 dark:text-forge-400">$0.1636</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default HeroA;
