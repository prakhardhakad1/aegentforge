"use client";
import { cn } from "@/lib/utils";

const SIZES = {
  xs: "h-3.5 w-3.5 border-[1.5px]",
  sm: "h-4 w-4 border-2",
  md: "h-6 w-6 border-2",
  lg: "h-9 w-9 border-[3px]",
} as const;

export function Spinner({
  size = "md",
  className,
  label,
}: {
  size?: keyof typeof SIZES;
  className?: string;
  label?: string;
}) {
  return (
    <span role="status" aria-live="polite" className={cn("inline-flex items-center gap-2", className)}>
      <span
        aria-hidden
        className={cn(
          "inline-block animate-spin rounded-full border-zinc-300 border-t-forge-500 dark:border-zinc-700 dark:border-t-forge-400",
          SIZES[size],
        )}
      />
      {label ? <span className="text-sm text-zinc-500 dark:text-zinc-400">{label}</span> : null}
    </span>
  );
}

export default Spinner;
