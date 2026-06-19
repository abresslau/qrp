"use client";

import { useState } from "react";

import { type Composition, rgbFor, textInk, useIsDark } from "@/components/portfolio-heatmap";

const TOOLTIP_TOP_N = 5; // per side (winners / losers) in the sector hover tooltip

// The sector breakdown is a HEAT MAP in the shape of a donut: each ring segment is a sector,
// sized by the sector's position size (Σ|weight|) and colored by its daily P&L (live return) on
// the SAME ±3% diverging scale as the heat-map treemap. Each segment carries an in-slice label —
// the sector name + its daily P&L — exactly like the treemap tiles (legend has the full list).

function polar(cx: number, cy: number, r: number, ang: number): [number, number] {
  return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
}

// One ring segment path. Angles in radians, clockwise from -90° (top). A near-full segment is
// nudged just under 2π so a single-slice (100%) donut still renders as a ring (no degenerate arc).
function donutArc(cx: number, cy: number, R: number, r: number, a0: number, a1: number): string {
  const span = Math.min(a1 - a0, Math.PI * 2 - 1e-3);
  const end = a0 + span;
  const large = span > Math.PI ? 1 : 0;
  const [x0o, y0o] = polar(cx, cy, R, a0);
  const [x1o, y1o] = polar(cx, cy, R, end);
  const [x1i, y1i] = polar(cx, cy, r, end);
  const [x0i, y0i] = polar(cx, cy, r, a0);
  return `M ${x0o} ${y0o} A ${R} ${R} 0 ${large} 1 ${x1o} ${y1o} L ${x1i} ${y1i} A ${r} ${r} 0 ${large} 0 ${x0i} ${y0i} Z`;
}

function wpct(w: number, dp = 1): string {
  return `${(w * 100).toFixed(dp)}%`;
}
function ret(r: number | null): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function retClass(r: number | null): string {
  if (r == null) return "text-muted";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

const S = 300;
const CX = S / 2;
const CY = S / 2;
const R = 140; // outer radius
const RI = 80; // inner radius (62px band — room for two lines of label)
const LABEL_R = (R + RI) / 2;
const LABEL_MIN_FRAC = 0.06; // smaller slices fall back to the legend (avoid label collisions)

export function PortfolioPizza({ data }: { data: Composition | null }) {
  const isDark = useIsDark();
  const [hover, setHover] = useState<{ sector: string; x: number; y: number } | null>(null);

  if (!data?.sectors?.length || !(data.total_weight > 0)) {
    return <p className="text-sm text-muted">No holdings to slice yet — upload a weight vector to see the sector breakdown.</p>;
  }

  const total = data.sectors.reduce((s, x) => s + x.weight, 0) || 1;
  const frac = (v: number) => v / total;
  const arcs = data.sectors.map((s, i) => {
    const prior = data.sectors.slice(0, i).reduce((acc, x) => acc + frac(x.weight), 0);
    const a0 = -Math.PI / 2 + prior * Math.PI * 2;
    const f = frac(s.weight);
    const a1 = a0 + f * Math.PI * 2;
    const mid = (a0 + a1) / 2;
    const rgb = rgbFor(s.live_return, isDark);
    const [lx, ly] = polar(CX, CY, LABEL_R, mid);
    return {
      s,
      frac: f,
      rgb,
      color: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`,
      d: donutArc(CX, CY, R, RI, a0, a1),
      lx,
      ly,
    };
  });

  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
        By sector — position size, colored by daily P&amp;L
      </h3>
      <div className="mt-2 flex flex-wrap items-center gap-6">
        <svg
          viewBox={`0 0 ${S} ${S}`}
          className="h-60 w-60 shrink-0"
          role="img"
          aria-label="Sector daily P&L donut heat map"
        >
          {arcs.map((a) => (
            <path
              key={a.s.sector}
              d={a.d}
              fill={a.color}
              stroke={isDark ? "#171717" : "#ffffff"}
              strokeWidth={1.5}
              className="cursor-pointer"
              onMouseEnter={(e) => setHover({ sector: a.s.sector, x: e.clientX, y: e.clientY })}
              onMouseMove={(e) => setHover({ sector: a.s.sector, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => setHover(null)}
            />
          ))}
          {arcs
            .filter((a) => a.frac >= LABEL_MIN_FRAC)
            .map((a) => {
              const ink = textInk(a.rgb);
              return (
                <g key={`label-${a.s.sector}`} className="pointer-events-none">
                  <text
                    x={a.lx}
                    y={a.ly - 4}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill={ink.fill}
                    fontSize={11}
                    fontWeight={600}
                    paintOrder="stroke"
                    stroke={ink.stroke}
                    strokeWidth={2}
                  >
                    {a.s.sector}
                  </text>
                  <text
                    x={a.lx}
                    y={a.ly + 11}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill={ink.fill}
                    fontSize={11}
                    paintOrder="stroke"
                    stroke={ink.stroke}
                    strokeWidth={2}
                  >
                    {ret(a.s.live_return)}
                  </text>
                </g>
              );
            })}
          <text x={CX} y={CY - 6} textAnchor="middle" className="fill-muted" fontSize={11}>
            gross
          </text>
          <text x={CX} y={CY + 12} textAnchor="middle" className="fill-fg" fontSize={16} fontWeight={700}>
            {wpct(data.total_weight)}
          </text>
        </svg>
        <ul className="min-w-[12rem] flex-1 space-y-1.5 text-xs">
          {arcs.map((a) => (
            <li key={a.s.sector} className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: a.color }} />
              <span className="truncate text-fg" title={a.s.sector}>
                {a.s.sector}
              </span>
              <span className="ml-auto shrink-0 tabular-nums text-muted">{wpct(a.frac)}</span>
              <span className={`w-16 shrink-0 text-right tabular-nums ${retClass(a.s.live_return)}`}>
                {ret(a.s.live_return)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {hover &&
        (() => {
          const hs = (data.holdings ?? []).filter((h) => h.sector === hover.sector && h.live_return != null);
          const movers = hs.map((h) => ({ t: h.ticker ?? h.figi, c: h.weight * (h.live_return as number) }));
          const winners = movers.filter((m) => m.c > 0).sort((a, b) => b.c - a.c).slice(0, TOOLTIP_TOP_N);
          const losers = movers.filter((m) => m.c < 0).sort((a, b) => a.c - b.c).slice(0, TOOLTIP_TOP_N);
          const w = typeof window !== "undefined" ? window.innerWidth : 1200;
          return (
            <div
              className="pointer-events-none fixed z-50 w-64 rounded-lg border border-border bg-bg p-3 text-fg shadow-xl"
              style={{ left: Math.min(hover.x + 14, w - 272), top: hover.y + 14 }}
            >
              <div className="text-[11px] uppercase tracking-wide text-muted">{hover.sector}</div>
              <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="text-[10px] font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                    Winners
                  </div>
                  {winners.length ? (
                    winners.map((m) => (
                      <div key={m.t} className="mt-0.5 flex justify-between gap-2">
                        <span className="truncate">{m.t}</span>
                        <span className="shrink-0 tabular-nums text-emerald-600 dark:text-emerald-400">{ret(m.c)}</span>
                      </div>
                    ))
                  ) : (
                    <div className="mt-0.5 text-muted">—</div>
                  )}
                </div>
                <div>
                  <div className="text-[10px] font-medium uppercase tracking-wide text-rose-600 dark:text-rose-400">
                    Losers
                  </div>
                  {losers.length ? (
                    losers.map((m) => (
                      <div key={m.t} className="mt-0.5 flex justify-between gap-2">
                        <span className="truncate">{m.t}</span>
                        <span className="shrink-0 tabular-nums text-rose-600 dark:text-rose-400">{ret(m.c)}</span>
                      </div>
                    ))
                  ) : (
                    <div className="mt-0.5 text-muted">—</div>
                  )}
                </div>
              </div>
              <div className="mt-2 text-[10px] text-muted">Top {TOOLTIP_TOP_N} by daily P&amp;L contribution</div>
            </div>
          );
        })()}
    </div>
  );
}
