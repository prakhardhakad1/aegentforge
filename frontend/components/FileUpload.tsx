"use client";
/**
 * FileUpload — drag-and-drop CSV dropzone plus a "paste a table" modal.
 * Produces a File for the parent to upload via POST /api/upload; the parent
 * owns the Dataset response and displays it.
 */
import { useRef, useState } from "react";
import { MAX_UPLOAD_MB } from "@/lib/api";
import { formatNumber } from "@/lib/utils";
import { Button } from "./Button";
import { Spinner } from "./Spinner";
import { cn } from "@/lib/utils";

export function FileUpload({
  uploading,
  onFileSelected,
  maxMb = MAX_UPLOAD_MB,
  className,
}: {
  uploading: boolean;
  onFileSelected: (file: File) => void;
  maxMb?: number;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [pasteError, setPasteError] = useState<string | null>(null);

  const accept = (file: File | undefined | null): string | null => {
    if (!file) return "No file selected.";
    const nameOk = /\.(csv|tsv|txt)$/i.test(file.name) || file.type.includes("csv") || file.type.includes("tab-separated") || file.type.includes("text/plain");
    if (!nameOk) return "Please choose a .csv file (or .tsv / .txt).";
    if (file.size > maxMb * 1024 * 1024) return `File is larger than ${maxMb} MB.`;
    return null;
  };

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    const err = accept(file);
    if (err || !file) return;
    onFileSelected(file);
  };

  const usePaste = () => {
    const text = pasteText.trim();
    const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
    if (lines.length < 2) {
      setPasteError("Paste a header row plus at least one data row.");
      return;
    }
    const file = new File([text], "pasted_table.csv", { type: "text/csv" });
    setPasteOpen(false);
    setPasteText("");
    setPasteError(null);
    onFileSelected(file);
  };

  return (
    <div className={className}>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a CSV file"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
          dragOver
            ? "border-forge-400 bg-forge-50/60 dark:border-forge-500/60 dark:bg-forge-500/10"
            : "border-zinc-300 hover:border-zinc-400 hover:bg-zinc-50 dark:border-white/15 dark:hover:border-white/25 dark:hover:bg-white/[0.03]",
        )}
      >
        {uploading ? (
          <Spinner label="Uploading and profiling…" />
        ) : (
          <>
            <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7 text-zinc-400 dark:text-zinc-500" aria-hidden>
              <path
                d="M12 16V4m0 0 4 4m-4-4L8 8m-4 9v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="mt-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              Drop a CSV here, or <span className="text-forge-600 dark:text-forge-400">browse</span>
            </p>
            <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
              Column profiles and quality notes are generated automatically · max {maxMb} MB
            </p>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.tsv,.txt,text/csv,text/plain"
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      <div className="mt-2 text-right">
        <button
          type="button"
          onClick={() => setPasteOpen(true)}
          className="text-xs font-medium text-forge-600 hover:underline dark:text-forge-400"
        >
          Or paste a table instead
        </button>
      </div>

      {/* paste-a-table modal */}
      {pasteOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/60 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Paste a table"
          onClick={(e) => {
            if (e.target === e.currentTarget) setPasteOpen(false);
          }}
        >
          <div className="w-full max-w-2xl rounded-2xl border border-zinc-200 bg-white p-5 shadow-xl dark:border-white/10 dark:bg-zinc-900">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Paste a table</h3>
              <button
                type="button"
                onClick={() => setPasteOpen(false)}
                aria-label="Close"
                className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-white/10"
              >
                <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
                  <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Copy straight from Excel / Google Sheets (tab-separated is fine) — first row must be the header.
            </p>
            <textarea
              value={pasteText}
              onChange={(e) => {
                setPasteText(e.target.value);
                setPasteError(null);
              }}
              rows={9}
              spellCheck={false}
              placeholder={"region,signups,revenue\nEMEA,1240,38200\nAMER,2310,71500\nAPAC,860,22100"}
              className="mt-3 w-full resize-y rounded-lg border border-zinc-300 bg-white p-3 font-mono text-xs text-zinc-800 placeholder:text-zinc-400 focus:border-forge-400 focus:outline-none focus:ring-2 focus:ring-forge-500/30 dark:border-white/15 dark:bg-zinc-950 dark:text-zinc-200 dark:placeholder:text-zinc-600"
            />
            {pasteError ? <p className="mt-2 text-xs text-rose-500">{pasteError}</p> : null}
            <div className="mt-3 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setPasteOpen(false)}>
                Cancel
              </Button>
              <Button size="sm" onClick={usePaste} disabled={!pasteText.trim()}>
                Use this table
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Compact read-only dataset summary card (used after upload succeeds). */
export function DatasetSummary({
  filename,
  rowCount,
  columns,
  qualityNotes,
  onRemove,
  className,
}: {
  filename: string;
  rowCount: number;
  columns: string[];
  qualityNotes: string[];
  onRemove?: () => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-400">
            <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
              <path d="m5 13 4 4L19 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{filename}</p>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              {formatNumber(rowCount)} rows · {columns.length} columns
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {columns.slice(0, 8).map((c) => (
                <span
                  key={c}
                  className="rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 ring-1 ring-inset ring-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:ring-white/10"
                >
                  {c}
                </span>
              ))}
              {columns.length > 8 ? (
                <span className="text-[10px] text-zinc-400 dark:text-zinc-500">+{columns.length - 8} more</span>
              ) : null}
            </div>
          </div>
        </div>
        {onRemove ? (
          <button
            type="button"
            onClick={onRemove}
            className="shrink-0 rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-white hover:text-rose-500 dark:hover:bg-white/10"
            aria-label="Remove dataset"
          >
            <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
              <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        ) : null}
      </div>
      {qualityNotes.length > 0 ? (
        <ul className="mt-3 space-y-1 border-t border-emerald-200/70 pt-2.5 dark:border-emerald-500/10">
          {qualityNotes.slice(0, 3).map((n, i) => (
            <li key={i} className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
              {n}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default FileUpload;
