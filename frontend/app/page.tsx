"use client";
/**
 * Landing (/) — hero (HeroA default, HeroB via /?hero=b), how-it-works,
 * template gallery preview, CTA. Templates load from GET /api/templates with
 * the demo-engine fallback handled inside lib/api.ts.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Template } from "@/lib/types";
import { Button } from "@/components/Button";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/Skeleton";
import { TemplateCard } from "@/components/TemplateCard";
import { HeroA } from "@/components/variants/HeroA";
import { HeroB } from "@/components/variants/HeroB";

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Describe the goal",
    body: "One plain-language sentence: \u201cWhy did churn spike in Q3?\u201d Attach a CSV or paste a table if you have data.",
  },
  {
    step: "02",
    title: "A planner hires the crew",
    body: "The planner agent decomposes your goal into a subtask DAG and assigns researcher, analyst and forecaster specialists.",
  },
  {
    step: "03",
    title: "Watch it work, live",
    body: "Every thought, tool call and artifact streams into the run view, with a per-agent token and cost meter ticking along.",
  },
  {
    step: "04",
    title: "Get a decision-ready report",
    body: "A critic stress-tests every claim, then you get ranked insights, charts, predictions and recommendations — Markdown or PDF.",
  },
];

export default function LandingPage() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [heroVariant, setHeroVariant] = useState<"a" | "b">("a");

  useEffect(() => {
    // Hero variant preview switch: /?hero=b (documented in NOTES.md).
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("hero") === "b") {
      setHeroVariant("b");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getTemplates()
      .then((res) => {
        if (cancelled) return;
        setTemplates(res.templates);
        setTemplatesError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setTemplatesError(err instanceof Error ? err.message : "Could not load teams.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      {heroVariant === "b" ? <HeroB /> : <HeroA />}

      {/* how it works */}
      <section className="border-t border-zinc-200 bg-white dark:border-white/10 dark:bg-zinc-900/40">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-forge-600 dark:text-forge-400">
            How it works
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
            From sentence to decision in four steps
          </h2>
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {HOW_IT_WORKS.map((s, i) => (
              <div
                key={s.step}
                className="animate-fade-up rounded-2xl border border-zinc-200 bg-zinc-50/60 p-5 dark:border-white/10 dark:bg-white/[0.03]"
                style={{ animationDelay: `${i * 90}ms` }}
              >
                <span className="font-mono text-xs font-bold text-forge-600 dark:text-forge-400">{s.step}</span>
                <h3 className="mt-2 text-sm font-bold text-zinc-900 dark:text-zinc-100">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* template gallery preview */}
      <section className="border-t border-zinc-200 dark:border-white/10">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-widest text-forge-600 dark:text-forge-400">
                Template marketplace
              </p>
              <h2 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
                Prebuilt teams, ready to hire
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-zinc-500 dark:text-zinc-400">
                Each template wires a full roster, a planner playbook and a report outline tuned to a kind of
                business question.
              </p>
            </div>
            <Button href="/templates" variant="secondary" size="sm">
              View all teams
            </Button>
          </div>
          <div className="mt-8 grid gap-5 md:grid-cols-3">
            {!templates ? (
              <>
                <SkeletonCard lines={4} />
                <SkeletonCard lines={4} />
                <SkeletonCard lines={4} />
              </>
            ) : templatesError ? (
              <div className="md:col-span-3">
                <ErrorState
                  title="Could not load the template gallery"
                  message={templatesError}
                  onRetry={() => {
                    setTemplates(null);
                    api
                      .getTemplates()
                      .then((res) => {
                        setTemplates(res.templates);
                        setTemplatesError(null);
                      })
                      .catch((e: unknown) =>
                        setTemplatesError(e instanceof Error ? e.message : "Could not load teams."),
                      );
                  }}
                />
              </div>
            ) : templates.length === 0 ? (
              <p className="md:col-span-3 text-center text-sm text-zinc-500 dark:text-zinc-400">
                No templates published yet.
              </p>
            ) : (
              templates.slice(0, 3).map((t) => <TemplateCard key={t.id} template={t} compact />)
            )}
          </div>
        </div>
      </section>

      {/* CTA band */}
      <section className="border-t border-zinc-200 bg-white dark:border-white/10 dark:bg-zinc-900/40">
        <div className="mx-auto max-w-7xl px-4 py-16 text-center sm:px-6 lg:px-8">
          <h2 className="text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
            Your next decision deserves a whole team.
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-zinc-500 dark:text-zinc-400">
            Spin up a mission in under a minute — watch the agents work, then ship the report to your stakeholders.
          </p>
          <div className="mt-6 flex justify-center">
            <Button href="/new" size="lg">
              Start a mission
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
