"use client";
/**
 * DemoBadge — honest mode indicator. Shows "Demo mode" when the demo engine
 * is serving API traffic (NEXT_PUBLIC_DEMO_MODE=1 or the backend is
 * unreachable), and a subtle live dot when the real API is responding.
 */
import { useEffect, useState } from "react";
import { demoActive, onDemoStateChange } from "@/lib/api";

export function DemoBadge() {
  const [demo, setDemo] = useState<boolean | null>(null);

  useEffect(() => {
    setDemo(demoActive());
    const off = onDemoStateChange((active) => setDemo(active));
    return () => {
      off();
    };
  }, []);

  if (demo === null) return null;

  if (demo) {
    return (
      <span
        title="Demo mode: the AgentForge API is not reachable, so a built-in simulation engine is serving realistic data."
        className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-700 ring-1 ring-inset ring-amber-300 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30"
      >
        <span aria-hidden className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-amber-500" />
        Demo mode
      </span>
    );
  }
  return (
    <span
      title="Connected to the AgentForge API."
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium text-zinc-400 dark:text-zinc-500"
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      Live
    </span>
  );
}

export default DemoBadge;
