"use client";
/**
 * /new — mission creator. Wraps MissionForm in Suspense because it reads
 * ?template=... via useSearchParams (required by the App Router).
 */
import { Suspense } from "react";
import { MissionForm } from "@/components/MissionForm";
import { Skeleton } from "@/components/Skeleton";

export default function NewMissionPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl dark:text-zinc-50">
          Describe your goal
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-500 dark:text-zinc-400">
          A planner will decompose it, hire the right specialists, and stream the work live. Attach data for
          quantitative analysis — it is optional.
        </p>
      </header>
      <Suspense
        fallback={
          <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
            <Skeleton className="h-72 rounded-2xl" />
            <Skeleton className="h-72 rounded-2xl" />
          </div>
        }
      >
        <MissionForm />
      </Suspense>
    </div>
  );
}
