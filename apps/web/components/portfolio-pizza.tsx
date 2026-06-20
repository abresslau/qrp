"use client";

import { useState } from "react";

import { type Composition, rgbFor, textInk, useIsDark } from "@/components/portfolio-heatmap";

const TOOLTIP_TOP_N = 5; // per side (winners / losers) in the sector hover tooltip

// The sector breakdown is a HEAT MAP in the shape of a donut: each ring segment is a sector,
// sized by position size (Σ|weight|), COLORED by the sector's daily move on the ±3% scale, and
// LABELLED by its daily P&L CONTRIBUTION (Σ w·r ÷ Σ|w| covered) — which sums to the portfolio's
// Daily P&L (the legend totals it). Hover a slice for that sector's top winners/losers.

function polar(cx: number, cy: number, r: number, ang: number): [number, number] {
  return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
}

// One ring segment path. Angles in radians, clockwise from -90° (top). A near-full segment is
// nudged just under 2π so a single-slice (100%) donut still renders as a ring.
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
const RI = 80; // inner radius
const LABEL_R = (R + RI) / 2;
const LABEL_MIN_FRAC = 0.06; // major slices: always labelled in-chart
const LABEL_MIN_MINOR = 0.035; // minor slices (≥3.5% but <6%): rendered but CSS-gated to wide containers

export function PortfolioPizza({ data }: { data: Composition | null }) {
  const isDark = useIsDark();
  const [hover, setHover] = useState<{ sector: string; x: number; y: number } | null>(null);

  if (!data?.sectors?.length || !(data.total_weight > 0)) {
    return <p className="text-sm text-muted">No holdings to slice yet — upload a weight vector to see the sector breakdown.</p>;
  }

  // Per-sector daily P&L CONTRIBUTION = Σ w·r ÷ Σ|w| covered. The per-sector values sum to the
  // portfolio Daily P&L (the same coverage-normalised roll-up the top panel shows).
  const priced = (data.holdings ?? []).filter((h) => h.live_return != null);
  const covered = priced.reduce((s, h) => s + Math.abs(h.weight), 0);
  const contribBySector: Record<string, number | null> = {};
  for (const s of data.sectors) {
    const hs = covered > 0 ? priced.filter((h) => h.sector === s.sector) : [];
    contribBySector[s.sector] = hs.length ? hs.reduce((acc, h) => acc + (h.weight * (h.live_return as number)) / covered, 0) : null;
  }
  const totalContrib = Object.values(contribBySector).reduce((acc: number, v) => acc + (v ?? 0), 0);

  const total = data.sectors.reduce((s, x) => s + x.weight, 0) || 1;
  const frac = (v: number) => v / total;
  const arcs = data.sectors.map((s, i) => {
    const prior = data.sectors.slice(0, i).reduce((acc, x) => acc + frac(x.weight), 0);
    const a0 = -Math.PI / 2 + prior * Math.PI * 2;
    const f = frac(s.weight);
    const a1 = a0 + f * Math.PI * 2;
    const mid = (a0 + a1) / 2;
    const rgb = rgbFor(s.live_return, isDark); // color = the sector's daily MOVE (vivid heat)
    const [lx, ly] = polar(CX, CY, LABEL_R, mid);
    return { s, frac: f, contrib: contribBySector[s.sector] ?? null, rgb, color: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`, d: donutArc(CX, CY, R, RI, a0, a1), lx, ly };
  });

  return (
    // @container: the donut sizes to THIS card's width (a container query), not the viewport — so
    // expanding the sidebar (which narrows the card, not the window) shrinks the donut to keep it
    // beside the legend and holds the card height, instead of wrapping the legend below.
    <div className="@container">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted">
        By sector — position size, daily P&amp;L
      </h3>
      <div className="mt-2 flex flex-wrap items-center gap-6">
        <svg viewBox={`0 0 ${S} ${S}`} className="h-52 w-52 shrink-0 @lg:h-64 @lg:w-64 @xl:h-72 @xl:w-72 @2xl:h-80 @2xl:w-80 @3xl:h-[24rem] @3xl:w-[24rem]" role="img" aria-label="Sector daily P&L donut heat map">
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
            .filter((a) => a.frac >= LABEL_MIN_MINOR)
            .map((a) => {
              const ink = textInk(a.rgb);
              // Minor slices (3.5–6%) are rendered but CSS-gated: shown only once the container is wide
              // (@2xl) and the ring has room; major slices (≥6%) are always labelled in-chart.
              const minor = a.frac < LABEL_MIN_FRAC;
              return (
                <g key={`label-${a.s.sector}`} className={minor ? "pointer-events-none hidden @2xl:block" : "pointer-events-none"}>
                  <text x={a.lx} y={a.ly - 4} textAnchor="middle" dominantBaseline="middle" fill={ink.fill} fontSize={11} fontWeight={600} paintOrder="stroke" stroke={ink.stroke} strokeWidth={2}>
                    {a.s.sector}
                  </text>
                  <text x={a.lx} y={a.ly + 11} textAnchor="middle" dominantBaseline="middle" fill={ink.fill} fontSize={11} paintOrder="stroke" stroke={ink.stroke} strokeWidth={2}>
                    {ret(a.contrib)}
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

        {/* Legend = a sector attribution table: weight + daily P&L contribution, totaling Daily P&L. */}
        <div className="min-w-[13rem] flex-1 text-xs">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted">
            <span className="h-2.5 w-2.5 shrink-0" aria-hidden />
            <span className="flex-1">Sector</span>
            <span className="w-12 text-right">Wt</span>
            <span className="w-16 text-right">P&amp;L</span>
          </div>
          <ul className="mt-1 space-y-1">
            {arcs.map((a) => (
              <li key={a.s.sector} className="flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: a.color }} />
                <span className="flex-1 truncate text-fg" title={a.s.sector}>
                  {a.s.sector}
                </span>
                <span className="w-12 shrink-0 text-right tabular-nums text-muted">{wpct(a.frac)}</span>
                <span className={`w-16 shrink-0 text-right tabular-nums ${retClass(a.contrib)}`}>{ret(a.contrib)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-1 flex items-center gap-2 border-t border-border pt-1 font-semibold">
            <span className="h-2.5 w-2.5 shrink-0" aria-hidden />
            <span className="flex-1 text-fg">Total</span>
            <span className="w-12 shrink-0 text-right tabular-nums text-muted">{wpct(1)}</span>
            <span className={`w-16 shrink-0 text-right tabular-nums ${retClass(totalContrib)}`}>{ret(totalContrib)}</span>
          </div>
        </div>
      </div>

      {hover &&
        (() => {
          const hs = priced.filter((h) => h.sector === hover.sector);
          const movers = hs.map((h) => ({ t: h.ticker ?? h.figi, c: covered > 0 ? (h.weight * (h.live_return as number)) / covered : 0 }));
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
                  <div className="text-[10px] font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400">Winners</div>
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
                  <div className="text-[10px] font-medium uppercase tracking-wide text-rose-600 dark:text-rose-400">Losers</div>
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
