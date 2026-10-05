"use client";
import { Button } from "@/components/Button";
import { ErrorState } from "@/components/ErrorState";

/** Global error boundary. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6 lg:px-8">
      <ErrorState
        title="Something broke while rendering this page"
        message={error.message || "An unexpected client-side error occurred."}
        onRetry={() => reset()}
        retryLabel="Reload this view"
      />
      <div className="mt-6 text-center">
        <Button href="/" variant="ghost" size="sm">
          Back to home
        </Button>
      </div>
    </div>
  );
}
