"use client";
/**
 * Minimal toast system: ToastProvider + useToast(). Renders a fixed stack at
 * bottom-right with success / error / info tones and auto-dismiss.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

type ToastTone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastApi {
  toast: (title: string, opts?: { tone?: ToastTone; description?: string; durationMs?: number }) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

const TONE_STYLES: Record<ToastTone, { ring: string; icon: React.ReactNode }> = {
  success: {
    ring: "ring-emerald-500/30 dark:ring-emerald-400/30",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 text-emerald-500" aria-hidden>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
        <path d="m8.5 12.5 2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  error: {
    ring: "ring-rose-500/30 dark:ring-rose-400/30",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 text-rose-500" aria-hidden>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 8v4.5m0 3h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
  info: {
    ring: "ring-sky-500/30 dark:ring-sky-400/30",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4 text-sky-500" aria-hidden>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 11v5m0-8h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    ),
  },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const toast = useCallback(
    (title: string, opts?: { tone?: ToastTone; description?: string; durationMs?: number }) => {
      idRef.current += 1;
      const id = idRef.current;
      const tone = opts?.tone ?? "info";
      setItems((prev) => [...prev.slice(-4), { id, tone, title, description: opts?.description }]);
      const timer = setTimeout(() => dismiss(id), opts?.durationMs ?? 4500);
      timersRef.current.set(id, timer);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      success: (title, description) => toast(title, { tone: "success", description }),
      error: (title, description) => toast(title, { tone: "error", description }),
      info: (title, description) => toast(title, { tone: "info", description }),
    }),
    [toast],
  );

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    };
  }, []);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2 px-2 sm:px-0"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className={cn(
              "pointer-events-auto flex animate-slide-in-right items-start gap-3 rounded-xl border border-zinc-200 bg-white p-3.5 shadow-lg ring-1 dark:border-white/10 dark:bg-zinc-900",
              TONE_STYLES[t.tone].ring,
            )}
          >
            <div className="mt-0.5 shrink-0">{TONE_STYLES[t.tone].icon}</div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{t.title}</p>
              {t.description ? (
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{t.description}</p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-white/10 dark:hover:text-zinc-200"
            >
              <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5" aria-hidden>
                <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export default ToastProvider;
