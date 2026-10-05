import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-zinc-200 py-8 dark:border-white/10">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 text-center sm:flex-row sm:px-6 sm:text-left lg:px-8">
        <p className="text-xs text-zinc-400 dark:text-zinc-500">
          AgentForge — Hire an AI team with one sentence. Built for ForgeHacks Online 2026 (AI + Business track).
        </p>
        <nav className="flex items-center gap-4 text-xs text-zinc-500 dark:text-zinc-400">
          <Link href="/new" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            New mission
          </Link>
          <Link href="/templates" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Teams
          </Link>
          <span className="text-zinc-300 dark:text-zinc-600">planner → workers → critic</span>
        </nav>
      </div>
    </footer>
  );
}

export default Footer;
