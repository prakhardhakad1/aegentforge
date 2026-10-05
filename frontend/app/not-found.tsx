import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-24 text-center sm:px-6 lg:px-8">
      <p className="font-mono text-sm font-semibold text-forge-600 dark:text-forge-400">404</p>
      <h1 className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">This page does not exist</h1>
      <p className="mt-2 max-w-md text-sm text-zinc-500 dark:text-zinc-400">
        The mission or run you are looking for may have a different URL — every run gets a unique id.
      </p>
      <div className="mt-6 flex gap-3">
        <Link
          href="/"
          className="inline-flex h-10 items-center rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-800 hover:bg-zinc-50 dark:border-white/15 dark:bg-white/5 dark:text-zinc-100 dark:hover:bg-white/10"
        >
          Back to home
        </Link>
        <Link
          href="/new"
          className="inline-flex h-10 items-center rounded-lg bg-gradient-to-b from-forge-500 to-forge-600 px-4 text-sm font-semibold text-white hover:from-forge-400 hover:to-forge-500"
        >
          Start a mission
        </Link>
      </div>
    </div>
  );
}
