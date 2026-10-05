"use client";
/**
 * ReportView — full structured report renderer: executive summary, ranked
 * insights, charts, predictions, ranked recommendations, appendix.
 * Download buttons are handled by the parent page via `onDownload`.
 */
import type { Report } from "@/lib/types";
import { renderMarkdown } from "@/lib/demo/markdown";
import { downloadText } from "@/lib/utils";
import { useToast } from "./Toaster";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { ChartBlock } from "./ChartBlock";
import { InsightCard } from "./InsightCard";
import { PredictionCard } from "./PredictionCard";
import { RecommendationTable } from "./RecommendationTable";
import { cn } from "@/lib/utils";

const STYLE_LABELS: Record<Report["style"], string> = {
  default: "Standard analysis",
  market_research: "Market research",
  sales_insights: "Sales insights",
  support_triage: "Support triage",
};

function SectionHeading({
  id,
  eyebrow,
  title,
  count,
}: {
  id: string;
  eyebrow: string;
  title: string;
  count?: number;
}) {
  return (
    <div id={id} className="scroll-mt-24">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-forge-600 dark:text-forge-400">{eyebrow}</p>
      <h2 className="mt-1 text-lg font-bold text-zinc-900 dark:text-zinc-50">
        {title}
        {count !== undefined ? <span className="ml-2 text-sm font-medium text-zinc-400 dark:text-zinc-500">({count})</span> : null}
      </h2>
    </div>
  );
}

export function ReportView({
  report,
  onDownload,
  downloading,
  className,
}: {
  report: Report;
  /** Called with "markdown" | "pdf" when a download button is clicked. */
  onDownload?: (format: "markdown" | "pdf") => void;
  downloading?: "markdown" | "pdf" | null;
  className?: string;
}) {
  const toastApi = useToast();

  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(renderMarkdown(report));
      toastApi.success("Markdown copied to clipboard");
    } catch {
      downloadText(renderMarkdown(report), "agentforge-report.md", "text/markdown;charset=utf-8");
      toastApi.info("Clipboard unavailable — downloaded the Markdown instead");
    }
  };

  return (
    <div className={cn("space-y-10", className)}>
      {/* header */}
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="forge">{STYLE_LABELS[report.style] ?? report.style}</Badge>
          <Badge tone="zinc">planner → workers → critic</Badge>
        </div>
        <h1 className="mt-3 text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
          {report.title}
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-zinc-500 dark:text-zinc-400">
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">Mission: </span>
          {report.mission}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onDownload?.("markdown")} loading={downloading === "markdown"}>
            <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5" aria-hidden>
              <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Markdown
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onDownload?.("pdf")} loading={downloading === "pdf"}>
            <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5" aria-hidden>
              <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            PDF
          </Button>
          <Button size="sm" variant="ghost" onClick={copyMarkdown}>
            Copy Markdown
          </Button>
        </div>
      </header>

      {/* executive summary */}
      <section className="rounded-2xl border border-forge-200/60 bg-gradient-to-br from-forge-50/80 to-transparent p-5 sm:p-6 dark:border-forge-500/20 dark:from-forge-500/[0.06] dark:to-transparent">
        <SectionHeading id="exec-summary" eyebrow="TL;DR" title="Executive summary" />
        <p className="mt-3 max-w-4xl text-[15px] leading-relaxed text-zinc-700 dark:text-zinc-300">
          {report.executive_summary}
        </p>
      </section>

      {/* insights */}
      <section>
        <SectionHeading id="insights" eyebrow="What we found" title="Key insights" count={report.insights.length} />
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {report.insights.map((ins, i) => (
            <InsightCard key={i} insight={ins} rank={i + 1} />
          ))}
        </div>
      </section>

      {/* charts */}
      {report.charts.length > 0 ? (
        <section>
          <SectionHeading id="charts" eyebrow="The data" title="Charts" count={report.charts.length} />
          <div className="mt-4 space-y-4">
            {report.charts.map((c) => (
              <ChartBlock key={c.id} spec={c} />
            ))}
          </div>
        </section>
      ) : null}

      {/* predictions */}
      {report.predictions.length > 0 ? (
        <section>
          <SectionHeading id="predictions" eyebrow="What happens next" title="Predictions" count={report.predictions.length} />
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {report.predictions.map((p, i) => (
              <PredictionCard key={i} prediction={p} />
            ))}
          </div>
        </section>
      ) : null}

      {/* recommendations */}
      {report.recommendations.length > 0 ? (
        <section>
          <SectionHeading id="recommendations" eyebrow="Do this" title="Ranked recommendations" count={report.recommendations.length} />
          <div className="mt-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-card dark:border-white/10 dark:bg-zinc-900/60">
            <RecommendationTable recommendations={report.recommendations} />
          </div>
        </section>
      ) : null}

      {/* appendix */}
      {report.appendix ? (
        <section>
          <details className="group rounded-2xl border border-zinc-200 bg-white dark:border-white/10 dark:bg-zinc-900/60">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              Appendix — method &amp; caveats
              <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 text-zinc-400 transition-transform group-open:rotate-180" aria-hidden>
                <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </summary>
            <p className="border-t border-zinc-100 px-5 py-4 text-sm leading-relaxed text-zinc-500 dark:border-white/5 dark:text-zinc-400">
              {report.appendix}
            </p>
          </details>
        </section>
      ) : null}
    </div>
  );
}

export default ReportView;
