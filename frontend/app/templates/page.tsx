"use client";
/**
 * /templates — template marketplace: one card per prebuilt team with the
 * roster, planner playbook (expected DAG), sample mission and a CTA.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Template } from "@/lib/types";
import { Button } from "@/components/Button";
import { ErrorState } from "@/components/ErrorState";
import { SkeletonCard } from "@/components/Skeleton";
import { TemplateCard } from "@/components/TemplateCard";

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getTemplates()
      .then((res) => {
        if (cancelled) return;
        setTemplates(res.templates);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not load teams.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8 max-w-2xl">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-forge-600 dark:text-forge-400">
          Template marketplace
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
          Pick a prebuilt AI team
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">
          Every team ships with a roster of specialists, a planner playbook (the execution DAG) and a report
          outline tuned to a type of business question.
        </p>
      </header>

      {!templates ? (
        <div className="grid gap-5 md:grid-cols-3">
          <SkeletonCard lines={5} />
          <SkeletonCard lines={5} />
          <SkeletonCard lines={5} />
        </div>
      ) : error ? (
        <ErrorState
          title="Could not load the marketplace"
          message={error}
          onRetry={() => {
            setTemplates(null);
            setError(null);
            api
              .getTemplates()
              .then((res) => setTemplates(res.templates))
              .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load teams."));
          }}
        />
      ) : templates.length === 0 ? (
        <p className="py-16 text-center text-sm text-zinc-500 dark:text-zinc-400">
          No templates published yet — the default balanced team is used when you start a mission without one.
        </p>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {templates.map((t) => (
            <TemplateCard key={t.id} template={t} />
          ))}
        </div>
      )}

      {!error && templates ? (
        <div className="mt-10 rounded-2xl border border-dashed border-zinc-300 p-6 text-center dark:border-white/15">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Need something bespoke? Start a mission without a template and the planner will compose a team for you.
          </p>
          <div className="mt-4">
            <Button href="/new" variant="secondary" size="sm">
              Compose a custom run
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
