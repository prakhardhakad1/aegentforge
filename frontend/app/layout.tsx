import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Footer } from "@/components/Footer";
import { Navbar } from "@/components/Navbar";
import { ToastProvider } from "@/components/Toaster";

export const metadata: Metadata = {
  title: {
    default: "AgentForge — Hire an AI team with one sentence",
    template: "%s · AgentForge",
  },
  description:
    "Describe a business goal; a planner spawns researcher, analyst, forecaster and critic agents that stream progress live and deliver insights, charts, predictions and ranked recommendations.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
  ],
};

/**
 * Inline theme bootstrap: runs before paint to avoid a flash of the wrong
 * theme. Default = system preference; explicit choice persisted in
 * localStorage("agentforge-theme") by the ThemeToggle.
 */
const THEME_BOOTSTRAP = `
try {
  var t = localStorage.getItem("agentforge-theme");
  var dark = t === "dark" || ((!t || t === "system") && window.matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) document.documentElement.classList.add("dark");
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="flex min-h-screen flex-col bg-zinc-50 font-sans text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <ToastProvider>
          <Navbar />
          <main className="flex-1">{children}</main>
          <Footer />
        </ToastProvider>
      </body>
    </html>
  );
}
