"use client";
/**
 * ChartBlock — renders the pinned ChartSpec (bar | line | scatter | pie) with
 * hand-rolled inline SVG. No chart library: keeps the bundle light and works
 * fully offline. Native <title> elements provide hover tooltips.
 */
import { useId } from "react";
import type { ChartSpec } from "@/lib/types";
import { cn } from "@/lib/utils";

const PALETTE = ["#f59e0b", "#38bdf8", "#34d399", "#a78bfa", "#fb7185", "#facc15", "#60a5fa", "#2dd4bf"];

const W = 640;

function fmtNum(n: number): string {
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1000) return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 10) return n.toFixed(1);
  return n.toFixed(2).replace(/\.?0+$/, "");
}

/** Round a max up to a "nice" value for the y-axis top tick. */
function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * exp;
}

function AxisLabels({ x, y }: { x: string; y: string }) {
  return (
    <>
      {y ? (
        <text
          transform={`rotate(-90)`}
          x={0}
          y={14}
          textAnchor="end"
          className="fill-zinc-400 dark:fill-zinc-500"
          fontSize="11"
        >
          {y}
        </text>
      ) : null}
      {x ? (
        <text
          x={W - 10}
          y={0}
          dy="4"
          textAnchor="end"
          className="fill-zinc-400 dark:fill-zinc-500"
          fontSize="11"
        >
          {x}
        </text>
      ) : null}
    </>
  );
}

/* ----------------------------- bar / line / scatter ---------------------- */

function CartesianChart({ spec, H }: { spec: ChartSpec; H: number }) {
  const uid = useId().replace(/[:]/g, "");
  const data = spec.data.filter((d) => Number.isFinite(d.y));
  const padL = 52;
  const padR = 14;
  const padT = 14;
  const padB = spec.data.length > 8 ? 58 : 40;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const maxVal = niceMax(Math.max(0, ...data.map((d) => d.y)));
  const ticks = 4;
  const tickVals = Array.from({ length: ticks + 1 }, (_, i) => (maxVal / ticks) * i);
  const yScale = (v: number) => padT + innerH - (Math.max(0, v) / maxVal) * innerH;

  const n = data.length;
  const band = n > 0 ? innerW / n : innerW;
  const labelEvery = Math.ceil(n / 12);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={spec.title}>
      <defs>
        <linearGradient id={`bar-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fe7a11" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.55" />
        </linearGradient>
        <linearGradient id={`area-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.02" />
        </linearGradient>
      </defs>

      {/* gridlines + y ticks */}
      {tickVals.map((tv) => (
        <g key={tv}>
          <line
            x1={padL}
            x2={W - padR}
            y1={yScale(tv)}
            y2={yScale(tv)}
            className="stroke-zinc-200 dark:stroke-white/10"
            strokeWidth="1"
          />
          <text
            x={padL - 8}
            y={yScale(tv)}
            dy="3.5"
            textAnchor="end"
            fontSize="10"
            className="fill-zinc-400 dark:fill-zinc-500"
          >
            {fmtNum(tv)}
          </text>
        </g>
      ))}

      {/* baseline */}
      <line
        x1={padL}
        x2={W - padR}
        y1={padT + innerH}
        y2={padT + innerH}
        className="stroke-zinc-300 dark:stroke-white/20"
        strokeWidth="1"
      />

      {spec.kind === "bar" &&
        data.map((d, i) => {
          const barW = Math.min(56, band * 0.62);
          const x = padL + band * i + (band - barW) / 2;
          const yTop = yScale(d.y);
          const h = Math.max(2, padT + innerH - yTop);
          return (
            <g key={`${d.label}-${i}`}>
              <rect x={x} y={yTop} width={barW} height={h} rx="4" fill={`url(#bar-${uid})`}>
                <title>{`${d.label}: ${fmtNum(d.y)}`}</title>
              </rect>
              {n <= 12 ? (
                <text
                  x={x + barW / 2}
                  y={yTop - 5}
                  textAnchor="middle"
                  fontSize="10"
                  className="fill-zinc-500 dark:fill-zinc-400"
                >
                  {fmtNum(d.y)}
                </text>
              ) : null}
            </g>
          );
        })}

      {spec.kind === "line" && (() => {
        const pts = data.map((d, i) => ({
          x: padL + (n === 1 ? innerW / 2 : (innerW / Math.max(1, n - 1)) * i),
          y: yScale(d.y),
          d,
        }));
        const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
        const area = `${line} L${pts[pts.length - 1].x.toFixed(1)},${(padT + innerH).toFixed(1)} L${pts[0].x.toFixed(1)},${(padT + innerH).toFixed(1)} Z`;
        return (
          <g>
            <path d={area} fill={`url(#area-${uid})`} />
            <path d={line} fill="none" stroke="#38bdf8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            {pts.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r="3.5" fill="#38bdf8" className="stroke-white dark:stroke-zinc-900" strokeWidth="1.5">
                <title>{`${p.d.label}: ${fmtNum(p.d.y)}`}</title>
              </circle>
            ))}
          </g>
        );
      })()}

      {spec.kind === "scatter" && (() => {
        const xs = data.map((d) => (Number.isFinite(d.x) ? d.x : 0));
        const xMax = niceMax(Math.max(1, ...xs));
        const xScale = (v: number) => padL + (Math.max(0, v) / xMax) * innerW;
        return (
          <g>
            {tickVals.slice(0, ticks).map((tv) => (
              <line
                key={`v${tv}`}
                x1={xScale((tv / maxVal) * xMax)}
                x2={xScale((tv / maxVal) * xMax)}
                y1={padT}
                y2={padT + innerH}
                className="stroke-zinc-200/60 dark:stroke-white/5"
                strokeWidth="1"
              />
            ))}
            {data.map((d, i) => (
              <circle
                key={i}
                cx={xScale(d.x)}
                cy={yScale(d.y)}
                r="6"
                fill={PALETTE[i % PALETTE.length]}
                fillOpacity="0.75"
                className="stroke-white dark:stroke-zinc-900"
                strokeWidth="1.5"
              >
                <title>{`${d.label}: (${fmtNum(d.x)}, ${fmtNum(d.y)})`}</title>
              </circle>
            ))}
          </g>
        );
      })()}

      {/* x labels */}
      {spec.kind !== "scatter" &&
        data.map((d, i) =>
          i % labelEvery === 0 ? (
            <text
              key={`xl-${i}`}
              x={spec.kind === "bar" ? padL + band * i + band / 2 : padL + (n === 1 ? innerW / 2 : (innerW / Math.max(1, n - 1)) * i)}
              y={padT + innerH + 16}
              textAnchor={n > 8 ? "end" : "middle"}
              transform={n > 8 ? `rotate(-35 ${spec.kind === "bar" ? padL + band * i + band / 2 : padL + (n === 1 ? innerW / 2 : (innerW / Math.max(1, n - 1)) * i)} ${padT + innerH + 16})` : undefined}
              fontSize="10"
              className="fill-zinc-500 dark:fill-zinc-400"
            >
              {d.label.length > 14 ? `${d.label.slice(0, 13)}…` : d.label}
            </text>
          ) : null,
        )}

      <AxisLabels x={spec.x_label} y={spec.y_label} />
    </svg>
  );
}

/* --------------------------------- pie ---------------------------------- */

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function PieChart({ spec, H }: { spec: ChartSpec; H: number }) {
  const data = spec.data.filter((d) => Number.isFinite(d.y) && d.y > 0);
  const total = data.reduce((acc, d) => acc + d.y, 0);
  if (!total) return null;
  const size = Math.min(H, 240);
  const cx = size / 2 + 10;
  const cy = size / 2 + 10;
  const r = size / 2 - 14;
  const rInner = r * 0.58;

  let angle = 0;
  const slices = data.map((d, i) => {
    const sweep = (d.y / total) * 360;
    const start = angle;
    const end = angle + sweep;
    angle = end;
    return { d, i, start, end, sweep };
  });

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <svg viewBox={`0 0 ${size + 20} ${size + 20}`} className="h-auto w-48 shrink-0 sm:w-56" role="img" aria-label={spec.title}>
        {slices.map(({ d, i, start, end, sweep }) => {
          if (sweep >= 359.99) {
            return (
              <circle key={i} cx={cx} cy={cy} r={(r + rInner) / 2} fill="none" stroke={PALETTE[0]} strokeWidth={r - rInner}>
                <title>{`${d.label}: ${fmtNum(d.y)} (${Math.round((d.y / total) * 100)}%)`}</title>
              </circle>
            );
          }
          const [x1, y1] = polar(cx, cy, r, start);
          const [x2, y2] = polar(cx, cy, r, end);
          const [x3, y3] = polar(cx, cy, rInner, end);
          const [x4, y4] = polar(cx, cy, rInner, start);
          const large = sweep > 180 ? 1 : 0;
          const path = `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)} L${x3.toFixed(2)},${y3.toFixed(2)} A${rInner},${rInner} 0 ${large} 0 ${x4.toFixed(2)},${y4.toFixed(2)} Z`;
          return (
            <path key={i} d={path} fill={PALETTE[i % PALETTE.length]} fillOpacity="0.9" className="stroke-white dark:stroke-zinc-950" strokeWidth="2">
              <title>{`${d.label}: ${fmtNum(d.y)} (${Math.round((d.y / total) * 100)}%)`}</title>
            </path>
          );
        })}
        <text x={cx} y={cy - 2} textAnchor="middle" fontSize="16" fontWeight="700" className="fill-zinc-800 dark:fill-zinc-100">
          {fmtNum(total)}
        </text>
        <text x={cx} y={cy + 14} textAnchor="middle" fontSize="9" className="fill-zinc-400 dark:fill-zinc-500">
          total
        </text>
      </svg>
      <ul className="min-w-0 flex-1 space-y-1.5">
        {slices.map(({ d, i }) => (
          <li key={i} className="flex items-center gap-2 text-sm">
            <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="min-w-0 flex-1 truncate text-zinc-700 dark:text-zinc-300">{d.label}</span>
            <span className="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">
              {Math.round((d.y / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------ container -------------------------------- */

export function ChartBlock({
  spec,
  height = 260,
  className,
}: {
  spec: ChartSpec;
  height?: number;
  className?: string;
}) {
  const data = Array.isArray(spec.data) ? spec.data : [];
  return (
    <figure className={cn("rounded-xl border border-zinc-200 bg-white p-4 dark:border-white/10 dark:bg-zinc-900/80", className)}>
      <figcaption className="mb-2 flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{spec.title}</span>
        <span className="shrink-0 rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-500 dark:bg-white/5 dark:text-zinc-400">
          {spec.kind}
        </span>
      </figcaption>
      {data.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-zinc-200 text-xs text-zinc-400 dark:border-white/10 dark:text-zinc-500">
          No data points for this chart.
        </div>
      ) : spec.kind === "pie" ? (
        <PieChart spec={spec} H={height} />
      ) : (
        <CartesianChart spec={{ ...spec, data }} H={height} />
      )}
      {spec.notes ? (
        <p className="mt-2 border-t border-zinc-100 pt-2 text-xs leading-relaxed text-zinc-500 dark:border-white/5 dark:text-zinc-400">
          {spec.notes}
        </p>
      ) : null}
    </figure>
  );
}

export default ChartBlock;
