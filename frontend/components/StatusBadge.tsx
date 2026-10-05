import { Badge } from "./Badge";
import type { RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_META: Record<RunStatus, { label: string; tone: "zinc" | "sky" | "emerald" | "rose" | "amber"; pulse: boolean }> = {
  queued: { label: "Queued", tone: "zinc", pulse: true },
  running: { label: "Running", tone: "sky", pulse: true },
  succeeded: { label: "Succeeded", tone: "emerald", pulse: false },
  failed: { label: "Failed", tone: "rose", pulse: false },
  partial: { label: "Partial", tone: "amber", pulse: false },
};

const DOT_COLORS: Record<RunStatus, string> = {
  queued: "bg-zinc-400",
  running: "bg-sky-500",
  succeeded: "bg-emerald-500",
  failed: "bg-rose-500",
  partial: "bg-amber-500",
};

export function StatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.queued;
  return (
    <Badge tone={meta.tone} className={cn("px-2.5 py-1", className)}>
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 rounded-full", DOT_COLORS[status], meta.pulse && "animate-pulse-dot")}
      />
      {meta.label}
    </Badge>
  );
}

export default StatusBadge;
