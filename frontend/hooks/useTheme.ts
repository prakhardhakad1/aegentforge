"use client";
/**
 * Theme handling: respects prefers-color-scheme by default (via the inline
 * bootstrap script in app/layout.tsx), persists an explicit override to
 * localStorage under "agentforge-theme", and toggles the `.dark` class on
 * <html> (Tailwind `darkMode: "class"`).
 */
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "agentforge-theme";
export type ThemeChoice = "light" | "dark" | "system";

function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return true;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readStored(): ThemeChoice {
  if (typeof window === "undefined") return "system";
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

function applyTheme(choice: ThemeChoice): void {
  const dark = choice === "dark" || (choice === "system" && systemPrefersDark());
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

export function useTheme(): {
  theme: ThemeChoice;
  resolved: "light" | "dark";
  setTheme: (t: ThemeChoice) => void;
  toggle: () => void;
  mounted: boolean;
} {
  const [theme, setThemeState] = useState<ThemeChoice>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = readStored();
    setThemeState(stored);
    applyTheme(stored);
    setResolved(
      stored === "dark" || (stored === "system" && systemPrefersDark()) ? "dark" : "light",
    );
    setMounted(true);

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (readStored() === "system") applyTheme("system");
      setResolved(systemPrefersDark() ? "dark" : "light");
    };
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  const setTheme = useCallback((t: ThemeChoice) => {
    setThemeState(t);
    try {
      window.localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* storage unavailable */
    }
    applyTheme(t);
    setResolved(t === "dark" || (t === "system" && systemPrefersDark()) ? "dark" : "light");
  }, []);

  const toggle = useCallback(() => {
    setTheme(resolved === "dark" ? "light" : "dark");
  }, [resolved, setTheme]);

  return { theme, resolved, setTheme, toggle, mounted };
}
