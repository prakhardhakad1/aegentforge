"use client";
/**
 * MissionForm — the /new mission creator: goal textarea, CSV upload (with
 * paste-a-table), sample-dataset chips, and team-template picker. On submit:
 * POST /api/missions → POST /api/missions/{id}/runs → navigate to the live run.
 */
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Dataset, Template } from "@/lib/types";
import { SAMPLE_DATASET_CHIPS, type SampleDatasetChip } from "@/lib/sampleDatasets";
import { Button } from "./Button";
import { Card } from "./Card";
import { AgentAvatar } from "./AgentAvatar";
import { DatasetSummary, FileUpload } from "./FileUpload";
import { Skeleton } from "./Skeleton";
import { useToast } from "./Toaster";
import { cn } from "@/lib/utils";

const GOAL_MIN = 12;
const GOAL_MAX = 2000;

export function MissionForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const toastApi = useToast();

  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [templateId, setTemplateId] = useState<string>("");
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Prefill template from ?template=... (TemplateCard / marketplace CTAs).
  useEffect(() => {
    const t = searchParams.get("template");
    if (t) setTemplateId(t);
  }, [searchParams]);

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

  const selectedTemplate = useMemo(
    () => templates?.find((t) => t.id === templateId) ?? null,
    [templates, templateId],
  );

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const ds = await api.uploadDataset(file);
      setDataset(ds);
      toastApi.success(`Loaded ${ds.filename}`, `${ds.row_count} rows · ${ds.columns.length} columns`);
    } catch (err) {
      toastApi.error("Upload failed", err instanceof Error ? err.message : "Unknown error");
    } finally {
      setUploading(false);
    }
  };

  const handleSampleChip = async (chip: SampleDatasetChip) => {
    setGoal(chip.goal);
    if (chip.templateId) setTemplateId(chip.templateId);
    if (dataset) setDataset(null);
    // Build the sample CSV in-browser and push it through the real upload path.
    const csv = chip.buildCsv();
    const file = new File([csv], chip.filename, { type: "text/csv" });
    await handleUpload(file);
  };

  const submit = async () => {
    const trimmed = goal.trim();
    if (trimmed.length < GOAL_MIN) {
      toastApi.error("Describe your goal in a bit more detail", `At least ${GOAL_MIN} characters.`);
      return;
    }
    setSubmitting(true);
    try {
      const mission = await api.createMission({
        goal: trimmed,
        template_id: templateId || null,
        dataset_id: dataset?.id ?? null,
      });
      const run = await api.startRun(mission.id);
      toastApi.success("Team hired — the run is starting");
      router.push(`/runs/${run.id}`);
    } catch (err) {
      toastApi.error("Could not start the run", err instanceof Error ? err.message : "Unknown error");
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      {/* main column */}
      <div className="space-y-6">
        <Card className="p-5 sm:p-6">
          <label htmlFor="goal" className="block text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Describe your goal
          </label>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            One sentence is enough — the planner turns it into a team plan.
          </p>
          <textarea
            id="goal"
            value={goal}
            maxLength={GOAL_MAX}
            onChange={(e) => setGoal(e.target.value)}
            rows={5}
            placeholder="e.g. Analyze why our churn spiked in Q3 and recommend 3 fixes with expected impact."
            className="mt-3 w-full resize-y rounded-xl border border-zinc-300 bg-white p-4 text-sm leading-relaxed text-zinc-900 placeholder:text-zinc-400 focus:border-forge-400 focus:outline-none focus:ring-2 focus:ring-forge-500/30 dark:border-white/15 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-600"
          />
          <div className="mt-1.5 flex items-center justify-between text-[11px] text-zinc-400 dark:text-zinc-500">
            <span>Attach data for deeper analysis — or run on public context alone.</span>
            <span className="tabular-nums">
              {goal.trim().length}/{GOAL_MAX}
            </span>
          </div>
        </Card>

        <Card className="p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Attach business data (optional)</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            The analyst runs real statistics on it; the forecaster projects from it.
          </p>
          <div className="mt-4">
            {dataset ? (
              <DatasetSummary
                filename={dataset.filename}
                rowCount={dataset.row_count}
                columns={dataset.columns}
                qualityNotes={dataset.quality_notes}
                onRemove={() => setDataset(null)}
              />
            ) : (
              <FileUpload uploading={uploading} onFileSelected={handleUpload} />
            )}
          </div>

          {/* sample dataset chips */}
          <div className="mt-4">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">
              No data handy? Try a sample dataset
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {SAMPLE_DATASET_CHIPS.map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  title={chip.description}
                  disabled={uploading || submitting}
                  onClick={() => void handleSampleChip(chip)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50",
                    dataset?.filename === chip.filename
                      ? "border-forge-400 bg-forge-50 text-forge-700 dark:border-forge-500/50 dark:bg-forge-500/10 dark:text-forge-300"
                      : "border-zinc-300 text-zinc-600 hover:border-zinc-400 hover:bg-zinc-50 dark:border-white/15 dark:text-zinc-300 dark:hover:bg-white/5",
                  )}
                >
                  {chip.label}
                </button>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* side column — template picker */}
      <div className="space-y-4">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Pick a team</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Templates pre-wire the planner&rsquo;s playbook. You can also leave it on auto.
          </p>
          {templatesError ? (
            <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600 dark:bg-rose-500/10 dark:text-rose-300">
              {templatesError} — you can still run with the default team.
            </p>
          ) : null}
          <div className="mt-3 space-y-2">
            {!templates ? (
              <>
                <Skeleton className="h-16 w-full rounded-xl" />
                <Skeleton className="h-16 w-full rounded-xl" />
                <Skeleton className="h-16 w-full rounded-xl" />
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setTemplateId("")}
                  className={cn(
                    "w-full rounded-xl border p-3 text-left transition-colors",
                    templateId === ""
                      ? "border-forge-400 bg-forge-50/70 dark:border-forge-500/50 dark:bg-forge-500/10"
                      : "border-zinc-200 hover:border-zinc-300 dark:border-white/10 dark:hover:border-white/20",
                  )}
                >
                  <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Auto — let the planner decide</p>
                  <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">A balanced crew for any goal.</p>
                </button>
                {templates.map((t) => {
                  const roster = Array.from(new Set(t.team.map((m) => m.role)));
                  const active = templateId === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setTemplateId(t.id)}
                      className={cn(
                        "w-full rounded-xl border p-3 text-left transition-colors",
                        active
                          ? "border-forge-400 bg-forge-50/70 dark:border-forge-500/50 dark:bg-forge-500/10"
                          : "border-zinc-200 hover:border-zinc-300 dark:border-white/10 dark:hover:border-white/20",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <div className="flex -space-x-1.5">
                          {roster.slice(0, 4).map((r) => (
                            <AgentAvatar key={r} role={r} size="xs" className="ring-2 ring-white dark:ring-zinc-900" />
                          ))}
                        </div>
                        <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{t.name}</p>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">{t.description}</p>
                    </button>
                  );
                })}
              </>
            )}
          </div>
        </Card>

        {selectedTemplate ? (
          <Card className="p-5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Planned flow</p>
            <ol className="mt-2 space-y-2">
              {selectedTemplate.expected_dag.map((n) => (
                <li key={n.id} className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                  <AgentAvatar role={n.agent} size="xs" />
                  <span className="min-w-0 flex-1 truncate">{n.title}</span>
                </li>
              ))}
            </ol>
          </Card>
        ) : null}

        <Button size="lg" className="w-full" onClick={submit} loading={submitting} disabled={goal.trim().length < GOAL_MIN}>
          Hire the team &amp; run
        </Button>
        <p className="text-center text-[11px] text-zinc-400 dark:text-zinc-500">
          You will watch the run live — planner, researchers, analyst, forecaster and critic stream as they work.
        </p>
      </div>
    </div>
  );
}

export default MissionForm;
