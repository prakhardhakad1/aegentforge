"use client";
/**
 * HeroB (variant B, not the default) — centered hero over a full-width
 * "pipeline" strip showing the five agents as a connected flow. Compare with
 * HeroA (recommended, split layout) by visiting /?hero=b.
 */
import Link from "next/link";
import { AGENT_META } from "@/lib/agents";
import { AGENT_ROLES } from "@/lib/types";
import { AgentAvatar } from "@/components/AgentAvatar";

const STEPS = [
  { role: "planner" as const, line: "Decompose the goal into a DAG" },
  { role: "researcher" as const, line: "Gather external evidence" },
  { role: "analyst" as const, line: "Crunch your data in Python" },
  { role: "forecaster" as const, line: "Project outcomes + confidence" },
  { role: "critic" as const, line: "Attack weak claims, rank the rest" },
];

export function HeroB() {
  return (
    <section className="relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[380px] bg-gradient-to-b from-forge-500/10 to-transparent dark:from-forge-500/15"
      />
      <div className="mx-auto max-w-4xl px-4 pb-14 pt-16 text-center sm:px-6 lg:pb-20 lg:pt-24 lg:px-8">
        <h1 className="animate-fade-up text-4xl font-extrabold leading-[1.08] tracking-tight text-zinc-900 sm:text-6xl dark:text-zinc-50">
          Hire an AI team with{" "}
          <span className="bg-gradient-to-r from-forge-500 via-orange-500 to-amber-400 bg-clip-text text-transparent">
            one sentence
          </span>
          .
        </h1>
        <p className="animate-fade-up mx-auto mt-5 max-w-2xl text-base leading-relaxed text-zinc-600 [animation-delay:120ms] sm:text-lg dark:text-zinc-400">
          A planner breaks your business goal into a plan, specialist agents execute it in
          parallel, and a critic stress-tests the result — streamed live, delivered as a
          decision-ready report.
        </p>
        <div className="animate-fade-up mt-8 flex flex-wrap items-center justify-center gap-3 [animation-delay:240ms]">
          <Link
            href="/new"
            className="inline-flex h-12 items-center rounded-xl bg-gradient-to-b from-forge-500 to-forge-600 px-7 text-base font-semibold text-white shadow-glow transition-all hover:from-forge-400 hover:to-forge-500"
          >
            Start a mission — free
          </Link>
          <Link
            href="/templates"
            className="inline-flex h-12 items-center rounded-xl border border-zinc-300 bg-white px-7 text-base font-medium text-zinc-800 transition-colors hover:bg-zinc-50 dark:border-white/15 dark:bg-white/5 dark:text-zinc-100 dark:hover:bg-white/10"
          >
            Browse AI teams
          </Link>
        </div>
      </div>

      {/* pipeline strip */}
      <div className="animate-fade-up mx-auto max-w-5xl px-4 pb-16 [animation-delay:360ms] sm:px-6 lg:px-8" aria-hidden>
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-xl dark:border-white/10 dark:bg-zinc-900">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
            {STEPS.map((s, i) => (
              <div key={s.role} className="relative flex flex-1 items-start gap-3 sm:flex-col sm:items-center sm:text-center">
                {i < STEPS.length - 1 ? (
                  <span className="absolute left-8 top-5 hidden h-0.5 w-[calc(100%-2rem)] sm:block">
                    <svg preserveAspectRatio="none" viewBox="0 0 100 2" className="h-0.5 w-full">
                      <line
                        x1="0"
                        y1="1"
                        x2="100"
                        y2="1"
                        stroke={AGENT_META[s.role].hex}
                        strokeOpacity="0.45"
                        strokeWidth="2"
                        strokeDasharray="6 5"
                        className="animate-dash-flow"
                      />
                    </svg>
                  </span>
                ) : null}
                <AgentAvatar role={s.role} size="lg" active={i === 1 || i === 2} />
                <div className="sm:mt-3">
                  <p className={`text-xs font-bold ${AGENT_META[s.role].text}`}>{AGENT_META[s.role].label}</p>
                  <p className="mt-0.5 text-[11px] leading-snug text-zinc-500 dark:text-zinc-400">{s.line}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export default HeroB;
