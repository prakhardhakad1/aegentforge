"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { DemoBadge } from "./DemoBadge";
import { ThemeToggle } from "./ThemeToggle";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/new", label: "New mission" },
  { href: "/templates", label: "Teams" },
];

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-forge-400 to-forge-600 text-white shadow-glow">
        <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
          <path
            d="M12 2.5c1.8 2.6 5.5 4.6 5.5 9a5.5 5.5 0 0 1-11 0c0-1.8.6-3.2 1.5-4.6.5 1 1.2 1.7 2 2.1-.4-2.4.5-4.9 2-6.5Z"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <span className="text-[15px] font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
        Agent<span className="text-forge-600 dark:text-forge-400">Forge</span>
      </span>
    </span>
  );
}

export function Navbar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-200/80 bg-white/85 backdrop-blur-md dark:border-white/10 dark:bg-zinc-950/80">
      <nav className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link href="/" aria-label="AgentForge home" onClick={() => setOpen(false)}>
          <Logo />
        </Link>
        <div className="ml-4 hidden items-center gap-1 sm:flex">
          {LINKS.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-zinc-100 text-zinc-900 dark:bg-white/10 dark:text-zinc-50"
                    : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100",
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <DemoBadge />
          <ThemeToggle />
          <Link
            href="/new"
            className="hidden items-center rounded-lg bg-gradient-to-b from-forge-500 to-forge-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:from-forge-400 hover:to-forge-500 sm:inline-flex"
          >
            Start a mission
          </Link>
          <button
            type="button"
            aria-label="Toggle menu"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/10 sm:hidden"
          >
            <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
              {open ? (
                <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              ) : (
                <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              )}
            </svg>
          </button>
        </div>
      </nav>
      {open ? (
        <div className="border-t border-zinc-200 px-4 py-2 sm:hidden dark:border-white/10">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              onClick={() => setOpen(false)}
              className="block rounded-lg px-3 py-2.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/5"
            >
              {l.label}
            </Link>
          ))}
          <Link
            href="/new"
            onClick={() => setOpen(false)}
            className="mt-1 block rounded-lg bg-forge-500 px-3 py-2.5 text-center text-sm font-semibold text-white"
          >
            Start a mission
          </Link>
        </div>
      ) : null}
    </header>
  );
}

export default Navbar;
