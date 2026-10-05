/**
 * Shared per-role visual metadata (colors + icons) used by AgentAvatar,
 * Timeline, EventLog and TokenMeter. Colors are distinct per pinned role:
 * planner / researcher / analyst / forecaster / critic.
 */
import type { AgentRole } from "@/lib/types";

export interface AgentMeta {
  role: AgentRole;
  label: string;
  /** One-line description of what this specialist does. */
  blurb: string;
  /** Solid hex, used for SVG strokes/fills in charts and meters. */
  hex: string;
  /** Tailwind text color class. */
  text: string;
  /** Tailwind background class for soft chips. */
  bg: string;
  /** Tailwind border class. */
  border: string;
  /** Gradient for avatars. */
  gradient: string;
  /** 24x24 viewBox stroke path for the role icon. */
  iconPath: string;
}

export const AGENT_META: Record<AgentRole, AgentMeta> = {
  planner: {
    role: "planner",
    label: "Planner",
    blurb: "Breaks the goal into a subtask DAG and assigns specialists.",
    hex: "#f59e0b",
    text: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-50 dark:bg-amber-500/10",
    border: "border-amber-200 dark:border-amber-500/20",
    gradient: "from-amber-400 to-orange-500",
    iconPath:
      "M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2m-6 9 2 2 4-4",
  },
  researcher: {
    role: "researcher",
    label: "Researcher",
    blurb: "Searches the web and summarizes sources with citations.",
    hex: "#38bdf8",
    text: "text-sky-600 dark:text-sky-400",
    bg: "bg-sky-50 dark:bg-sky-500/10",
    border: "border-sky-200 dark:border-sky-500/20",
    gradient: "from-sky-400 to-blue-500",
    iconPath: "M21 21l-4.35-4.35M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
  },
  analyst: {
    role: "analyst",
    label: "Analyst",
    blurb: "Runs Python on your data: stats, trends, charts.",
    hex: "#34d399",
    text: "text-emerald-600 dark:text-emerald-400",
    bg: "bg-emerald-50 dark:bg-emerald-500/10",
    border: "border-emerald-200 dark:border-emerald-500/20",
    gradient: "from-emerald-400 to-teal-500",
    iconPath: "M4 20h16M7 16v-5m5 5V8m5 8v-8",
  },
  forecaster: {
    role: "forecaster",
    label: "Forecaster",
    blurb: "Projects what happens next, with confidence and basis.",
    hex: "#a78bfa",
    text: "text-violet-600 dark:text-violet-400",
    bg: "bg-violet-50 dark:bg-violet-500/10",
    border: "border-violet-200 dark:border-violet-500/20",
    gradient: "from-violet-400 to-purple-500",
    iconPath: "M3 17l6-6 4 4 7-7m0 0h-5m5 0v5",
  },
  critic: {
    role: "critic",
    label: "Critic",
    blurb: "Stress-tests every claim, flags weak evidence, ranks findings.",
    hex: "#fb7185",
    text: "text-rose-600 dark:text-rose-400",
    bg: "bg-rose-50 dark:bg-rose-500/10",
    border: "border-rose-200 dark:border-rose-500/20",
    gradient: "from-rose-400 to-pink-500",
    iconPath:
      "M9 12l2 2 4-4m5.6-2.4.8 3.6a6 6 0 0 1-3.4 6.7L12 21l-6-3.1a6 6 0 0 1-3.4-6.7l.8-3.6L12 3l9.4 3.6Z",
  },
};

export function agentLabel(role: string | null | undefined): string {
  if (!role) return "System";
  return AGENT_META[role as AgentRole]?.label ?? role;
}

export function agentColor(role: string | null | undefined): string {
  if (!role) return "#71717a";
  return AGENT_META[role as AgentRole]?.hex ?? "#71717a";
}
