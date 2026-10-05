"use client";
import { useTheme } from "@/hooks/useTheme";

/** Light/dark toggle. Falls back to system preference; persists the choice. */
export function ThemeToggle() {
  const { resolved, toggle, mounted } = useTheme();
  if (!mounted) {
    return <span className="inline-block h-9 w-9" aria-hidden />;
  }
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-zinc-100"
    >
      {resolved === "dark" ? (
        <svg viewBox="0 0 24 24" fill="none" className="h-[18px] w-[18px]" aria-hidden>
          <circle cx="12" cy="12" r="4.2" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M12 2.8v2.4m0 13.6v2.4M21.2 12h-2.4M5.2 12H2.8m15.8-6.6-1.7 1.7M7.1 16.9l-1.7 1.7m0-13.2 1.7 1.7m9.8 9.8 1.7 1.7"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" className="h-[18px] w-[18px]" aria-hidden>
          <path
            d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  );
}

export default ThemeToggle;
