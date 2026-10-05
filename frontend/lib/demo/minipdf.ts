/**
 * Minimal PDF writer (no dependencies) + Report → PDF layout.
 *
 * Used only in demo mode when the backend (which renders PDFs with fpdf2 per
 * INTERFACES.md) is unavailable. Produces a valid PDF 1.4 with Helvetica text.
 */
import type { Report } from "@/lib/types";

const PAGE_W = 612; // US Letter, points
const PAGE_H = 792;
const MARGIN = 56;
const MAX_W = PAGE_W - MARGIN * 2;

export interface PdfBlock {
  text: string;
  size?: number;
  bold?: boolean;
  /** Extra vertical gap before the block, in points. */
  gap?: number;
}

/* ------------------------------------------------------------------ */
/* Text prep                                                           */
/* ------------------------------------------------------------------ */

const CHAR_MAP: Record<string, string> = {
  "\u2018": "'",
  "\u2019": "'",
  "\u201C": '"',
  "\u201D": '"',
  "\u2013": "-",
  "\u2014": "-",
  "\u2026": "...",
  "\u20AC": "EUR ",
  "\u2192": "->",
  "\u00D7": "x",
  "\u2264": "<=",
  "\u00B1": "+/-",
  "\u2022": "-",
  "\t": "    ",
};

function toAscii(s: string): string {
  let out = "";
  for (const ch of s) {
    if (ch === "\n") {
      out += "\n";
      continue;
    }
    const mapped = CHAR_MAP[ch];
    if (mapped !== undefined) {
      out += mapped;
    } else if (ch >= " " && ch <= "~") {
      out += ch;
    } else {
      out += " ";
    }
  }
  return out;
}

function esc(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

/** Greedy word-wrap: approximate Helvetica advance at ~0.5 × size per char. */
function wrap(text: string, size: number): string[] {
  const perLine = Math.max(20, Math.floor(MAX_W / (size * 0.5)));
  const lines: string[] = [];
  for (const paragraph of text.split("\n")) {
    const words = paragraph.split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      lines.push("");
      continue;
    }
    let cur = "";
    for (const w of words) {
      if (cur.length === 0) cur = w;
      else if (cur.length + 1 + w.length <= perLine) cur += ` ${w}`;
      else {
        lines.push(cur);
        cur = w;
      }
    }
    if (cur) lines.push(cur);
  }
  return lines;
}

/* ------------------------------------------------------------------ */
/* PDF assembly                                                        */
/* ------------------------------------------------------------------ */

export function buildPdf(blocks: PdfBlock[]): Uint8Array<ArrayBuffer> {
  // --- paginate -------------------------------------------------------
  const pageContents: string[] = [];
  let current: string[] = [];
  let cursor = PAGE_H - MARGIN;

  const pushLine = (text: string, size: number, bold: boolean) => {
    const lh = Math.round(size * 1.5);
    if (cursor - lh < MARGIN) {
      pageContents.push(current.join("\n"));
      current = [];
      cursor = PAGE_H - MARGIN;
    }
    cursor -= lh;
    const font = bold ? "/F2" : "/F1";
    current.push(
      `BT ${font} ${size} Tf 1 0 0 1 ${MARGIN} ${Math.round(cursor)} Tm (${esc(text)}) Tj ET`,
    );
  };

  for (const b of blocks) {
    const size = b.size ?? 10;
    cursor -= b.gap ?? 0;
    for (const rawLine of toAscii(b.text).split("\n")) {
      for (const line of wrap(rawLine, size)) {
        pushLine(line, size, b.bold ?? false);
      }
    }
  }
  pageContents.push(current.join("\n"));

  // --- object table ---------------------------------------------------
  const objects: string[] = [];
  objects[0] = ""; // placeholder; objects are 1-indexed
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>";
  objects[4] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>";

  const firstPageObj = 5;
  const kids = pageContents.map((_, i) => `${firstPageObj + i * 2} 0 R`).join(" ");
  objects[2] = `<< /Type /Pages /Kids [${kids}] /Count ${pageContents.length} >>`;

  pageContents.forEach((content, i) => {
    const pageObj = firstPageObj + i * 2;
    const contentObj = pageObj + 1;
    objects[pageObj] =
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] ` +
      `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentObj} 0 R >>`;
    objects[contentObj] = `<< /Length ${content.length} >>\nstream\n${content}\nendstream`;
  });

  // --- serialize ------------------------------------------------------
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  for (let i = 1; i < objects.length; i++) {
    offsets[i] = out.length;
    out += `${i} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const xrefStart = out.length;
  out += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let i = 1; i < objects.length; i++) {
    out += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  }
  out += `trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF\n`;

  const buffer = new ArrayBuffer(out.length);
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xff;
  return bytes;
}

/* ------------------------------------------------------------------ */
/* Report → PDF blocks                                                 */
/* ------------------------------------------------------------------ */

function insightStrengthLabel(s: Report["insights"][number]["strength"]): string {
  return s === "high" ? "Strong evidence" : s === "medium" ? "Medium evidence" : "Weak evidence";
}

export function reportToPdfBlocks(report: Report): PdfBlock[] {
  const blocks: PdfBlock[] = [];
  blocks.push({ text: report.title, size: 18, bold: true, gap: 6 });
  blocks.push({ text: `Mission: ${report.mission}`, size: 10, gap: 2 });
  blocks.push({ text: "AGENTFORGE — demo-mode PDF export (simulated data)", size: 8, gap: 2 });

  blocks.push({ text: "Executive summary", size: 14, bold: true, gap: 14 });
  blocks.push({ text: report.executive_summary, size: 10 });

  blocks.push({ text: "Key insights (ranked)", size: 14, bold: true, gap: 14 });
  report.insights.forEach((ins, i) => {
    blocks.push({ text: `${i + 1}. ${ins.title}  [${insightStrengthLabel(ins.strength)}]`, size: 11, bold: true, gap: 8 });
    blocks.push({ text: ins.detail, size: 10 });
    if (ins.evidence.length) {
      blocks.push({ text: `Evidence: ${ins.evidence.map((e) => `- ${e}`).join(" ")}`, size: 9 });
    }
  });

  if (report.charts.length) {
    blocks.push({ text: "Charts", size: 14, bold: true, gap: 14 });
    for (const c of report.charts) {
      blocks.push({ text: c.title, size: 11, bold: true, gap: 8 });
      blocks.push({ text: `(${c.kind} chart — ${c.x_label || "x"} vs ${c.y_label || "y"})`, size: 9 });
      for (const p of c.data) {
        blocks.push({ text: `  ${p.label}: ${p.y}`, size: 9 });
      }
      if (c.notes) blocks.push({ text: c.notes, size: 9 });
    }
  }

  if (report.predictions.length) {
    blocks.push({ text: "Predictions", size: 14, bold: true, gap: 14 });
    report.predictions.forEach((p, i) => {
      blocks.push({ text: `${i + 1}. ${p.claim}`, size: 11, bold: true, gap: 8 });
      blocks.push({ text: `Confidence: ${Math.round(p.confidence * 100)}% — ${p.basis}`, size: 10 });
    });
  }

  if (report.recommendations.length) {
    blocks.push({ text: "Ranked recommendations", size: 14, bold: true, gap: 14 });
    [...report.recommendations]
      .sort((a, b) => a.priority - b.priority)
      .forEach((r) => {
        blocks.push({ text: `#${r.priority} ${r.title} (effort: ${r.effort})`, size: 11, bold: true, gap: 8 });
        blocks.push({ text: `Action: ${r.action}`, size: 10 });
        blocks.push({ text: `Expected impact: ${r.expected_impact}`, size: 10 });
      });
  }

  if (report.appendix) {
    blocks.push({ text: "Appendix — method & caveats", size: 14, bold: true, gap: 14 });
    blocks.push({ text: report.appendix, size: 9 });
  }

  return blocks;
}
