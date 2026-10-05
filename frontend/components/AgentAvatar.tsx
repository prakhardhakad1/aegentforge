import { AGENT_META } from "@/lib/agents";
import type { AgentRole } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIZES = {
  xs: { box: "h-5 w-5", icon: "h-3 w-3" },
  sm: { box: "h-7 w-7", icon: "h-3.5 w-3.5" },
  md: { box: "h-9 w-9", icon: "h-[18px] w-[18px]" },
  lg: { box: "h-12 w-12", icon: "h-6 w-6" },
} as const;

export function AgentAvatar({
  role,
  size = "md",
  active = false,
  dimmed = false,
  className,
  title,
}: {
  role: AgentRole;
  size?: keyof typeof SIZES;
  /** Adds an animated ring while the agent is mid-task. */
  active?: boolean;
  dimmed?: boolean;
  className?: string;
  title?: string;
}) {
  const meta = AGENT_META[role];
  const s = SIZES[size];
  return (
    <span
      title={title ?? `${meta.label} — ${meta.blurb}`}
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-white shadow-sm transition-opacity",
        meta.gradient,
        s.box,
        dimmed && "opacity-40 saturate-50",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" fill="none" className={s.icon} aria-hidden>
        <path
          d={meta.iconPath}
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {active ? (
        <span
          aria-hidden
          className={cn(
            "absolute -inset-1 animate-ping rounded-full border-2 opacity-60",
            meta.border,
          )}
          style={{ borderColor: meta.hex }}
        />
      ) : null}
    </span>
  );
}

export default AgentAvatar;
