import { cn } from "@/lib/utils";

/** Rectangular shimmer placeholder. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "animate-shimmer rounded-md bg-gradient-to-r from-zinc-200 via-zinc-100 to-zinc-200 bg-[length:700px_100%] dark:from-zinc-800 dark:via-zinc-700/60 dark:to-zinc-800",
        className,
      )}
    />
  );
}

/** Composed card-shaped loading block. */
export function SkeletonCard({ className, lines = 3 }: { className?: string; lines?: number }) {
  return (
    <div className={cn("rounded-2xl border border-zinc-200 bg-white p-5 dark:border-white/10 dark:bg-zinc-900/60", className)}>
      <Skeleton className="h-4 w-1/3" />
      <div className="mt-4 space-y-2.5">
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton key={i} className={cn("h-3", i === lines - 1 ? "w-2/3" : "w-full")} />
        ))}
      </div>
    </div>
  );
}

export default Skeleton;
