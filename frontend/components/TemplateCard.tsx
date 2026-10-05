"use client";
import Link from "next/link";
import { AGENT_META } from "@/lib/agents";
import type { Template } from "@/lib/types";
import { AgentAvatar } from "./AgentAvatar";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { cn } from "@/lib/utils";

/**
 * TemplateCard — marketplace card for a prebuilt AI team: roster, tags,
 * sample mission, and a "Use this team" CTA into /new?template=...
 * `compact` trims it down for the landing-page gallery preview.
 */
export function TemplateCard({
  template,
  compact = false,
  className,
}: {
  template: Template;
  compact?: boolean;
  className?: string;
}) {
  // Distinct roles only for the roster strip (a team may repeat a role).
  const roster = Array.from(new Set(template.team.map((m) => m.role)));
  return (
    <article
      className={cn(
        "group flex h-full flex-col rounded-2xl border border-zinc-200 bg-white p-5 shadow-card transition-shadow hover:shadow-lg dark:border-white/10 dark:bg-zinc-900/60",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {roster.slice(0, 5).map((r) => (
          <AgentAvatar key={r} role={r} size="sm" />
        ))}
        {roster.length > 5 ? (
          <span className="text-xs text-zinc-400 dark:text-zinc-500">+{roster.length - 5}</span>
        ) : null}
      </div>
      <h3 className="mt-3 text-base font-bold text-zinc-900 dark:text-zinc-50">{template.name}</h3>
      <p className="mt-1.5 flex-1 text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">{template.description}</p>

      {/* roster with titles */}
      {!compact ? (
        <ul className="mt-4 space-y-1.5 border-t border-zinc-100 pt-3 dark:border-white/5">
          {template.team.map((m, i) => (
            <li key={`${m.role}-${i}`} className="flex items-center gap-2 text-xs">
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full")} style={{ background: AGENT_META[m.role].hex }} />
              <span className={cn("font-semibold", AGENT_META[m.role].text)}>{AGENT_META[m.role].label}</span>
              <span className="truncate text-zinc-500 dark:text-zinc-400">— {m.title}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {/* sample mission */}
      <div className="mt-4 rounded-xl bg-zinc-50 p-3 dark:bg-white/[0.04]">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500">Sample mission</p>
        <p className={cn("mt-1 text-xs italic leading-relaxed text-zinc-600 dark:text-zinc-400", compact && "line-clamp-2")}>
          &ldquo;{template.sample_mission}&rdquo;
        </p>
      </div>

      {/* tags */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {template.tags.slice(0, compact ? 3 : undefined).map((t) => (
          <Badge key={t} tone="zinc">
            {t}
          </Badge>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-2 pt-1">
        <Button href={`/new?template=${template.id}`} size="sm" className="flex-1">
          Use this team
        </Button>
        {!compact ? (
          <Link
            href={`/new?template=${template.id}`}
            className="rounded-lg px-2 py-2 text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            Preview plan
          </Link>
        ) : null}
      </div>
    </article>
  );
}

export default TemplateCard;
