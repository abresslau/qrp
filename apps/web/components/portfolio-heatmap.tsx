"use client";

import { hierarchy, treemap, treemapSquarify } from "d3-hierarchy";
import { useEffect, useMemo, useRef, useState } from "react";

// Live composition of a portfolio (story portfolios-live-heatmap-and-pizza). These local types
// mirror the analytics `PortfolioComposition` response; the component is presentational (the page
// owns the single fetch and passes `data`), so nothing here is bound to generated `Schemas` —
// same convention as heatmap-view.tsx.
export type CompositionHolding = {
  figi: string;
  ticker: string | null;
  name: string | null;
  sector: string;
  industry: string | null;
  mic: string | null;
  country: string | null;
  country_iso?: string | null; // FactSet region (ADS-DE)
  exch_code?: string | null; // Bloomberg region (ADS GR)
  bbg_exchange_code?: string | null; // Bloomberg venue (ADS GY)
  status: string | null;
  weight: number; // SIGNED — position size is abs(weight)
  currency: string | null;
  market_cap_usd: number | null;
  volume: number | null;
  price: number | null;
  live_return: number | null;
  // trailing 1D/1M/3M/6M returns re-based to the live price (plain EOD when not priced; null otherwise)
  window_returns: Record<string, number | null>;
  // 52-week range: trailing-52w adjusted-close low/high and where the current price sits in it
  // (0 = at the low, 1 = at the high). null when no extremes row.
  low_52w: number | null;
  high_52w: number | null;
  range_pct: number | null;
  freshness: string;
};
export type SectorSlice = {
  sector: string;
  weight: number; // Σ |weight| of the sector
  n: number;
  live_return: number | null;
};
export type Composition = {
  portfolio_id: number;
  weights_as_of: string | null;
  as_of: string | null;
  freshness: string;
  n_holdings: number;
  n_priced: number;
  total_weight: number; // gross Σ|weight|
  net_weight: number; // net Σ weight
  holdings: CompositionHolding[];
  sectors: SectorSlice[];
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Node = any;

const W = 1000;
// Flatter aspect (was 460) so the full-width heat map stays short enough that the live cockpit —
// header P&L + donut + movers + heat map — fits a full-screen window without scrolling. Height of the
// rendered SVG ≈ (H/W) × card width, so a smaller H buys back vertical space, more so on wide screens.
const H = 300;
const HEADER = 16;
const CLAMP = 0.03; // ±3% saturates the diverging scale (matches heatmap-view + the legend)

// Diverging scale: red (neg) -> neutral (~0) -> green (pos); the neutral midpoint follows the theme.
// Exported so the sector donut paints its slices on the SAME ±3% heat scale (a heat map in a ring).
export function rgbFor(ret: number | null, isDark: boolean): [number, number, number] {
  const mid = isDark ? [42, 42, 48] : [228, 228, 231];
  if (ret == null) return isDark ? [55, 55, 62] : [203, 205, 209]; // no live return -> neutral
  const t = Math.max(-1, Math.min(1, ret / CLAMP));
  const neg = [224, 72, 90];
  const pos = [63, 174, 90];
  const tgt = t < 0 ? neg : pos;
  const u = Math.abs(t);
  const m = (a: number, b: number) => Math.round(a + (b - a) * u);
  return [m(mid[0], tgt[0]), m(mid[1], tgt[1]), m(mid[2], tgt[2])];
}

export function useIsDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const el = document.documentElement;
    const update = () => setDark(el.classList.contains("dark"));
    update();
    const obs = new MutationObserver(update);
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

export function textInk([r, g, b]: [number, number, number]): { fill: string; stroke: string } {
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  return lum > 150
    ? { fill: "#111827", stroke: "rgba(255,255,255,0.35)" }
    : { fill: "#ffffff", stroke: "rgba(0,0,0,0.40)" };
}

function pct(r: number | null): string {
  return r == null ? "" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function wpct(w: number): string {
  return `${w >= 0 ? "" : "−"}${(Math.abs(w) * 100).toFixed(1)}%`;
}

export function PortfolioHeatmap({ data }: { data: Composition | null }) {
  const isDark = useIsDark();
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<CompositionHolding | null>(null);
  const [pos, setPos] = useState<{ x: number; y: number; w: number }>({ x: 0, y: 0, w: 0 });

  const root = useMemo<Node>(() => {
    if (!data?.holdings?.length || !(data.total_weight > 0)) return null;
    const groups: Record<string, CompositionHolding[]> = {};
    for (const h of data.holdings) (groups[h.sector] ||= []).push(h);
    // Sectors sized by Σ|weight| (a sector is as big as its total position size), tiles by |weight|.
    const sectors = Object.entries(groups).map(([name, hs]) => {
      let wsum = 0;
      let rsum = 0;
      for (const h of hs) {
        if (h.live_return != null) {
          wsum += Math.abs(h.weight);
          rsum += Math.abs(h.weight) * h.live_return;
        }
      }
      return {
        name,
        sectorRet: wsum > 0 ? rsum / wsum : null,
        children: hs.map((h) => ({ ...h, value: Math.abs(h.weight) })),
      };
    });
    const h = hierarchy<Node>({ name: "root", children: sectors })
      .sum((d: Node) => d.value ?? 0)
      .sort((a: Node, b: Node) => (b.value ?? 0) - (a.value ?? 0));
    treemap<Node>()
      .tile(treemapSquarify)
      .size([W, H])
      .paddingInner(1)
      .paddingOuter(2)
      .paddingTop((d: Node) => (d.depth === 1 ? HEADER : 0))
      .round(true)(h);
    return h;
  }, [data]);

  if (!data?.holdings?.length || !(data.total_weight > 0)) {
    return (
      <div className="rounded-xl border border-border bg-surface p-6 text-sm text-muted">
        No holdings to map yet — upload a weight vector to see the live heat map.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative rounded-xl border border-border bg-surface p-2"
      onMouseMove={(e) => {
        const r = containerRef.current?.getBoundingClientRect();
        if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width });
      }}
      onMouseLeave={() => setHover(null)}
    >
      {root && (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block w-full"
          role="img"
          aria-label="Portfolio heat map treemap — sized by position size, colored by live return"
        >
          <rect x={0} y={0} width={W} height={H} fill={isDark ? "#171717" : "#f6f7f9"} />
          {(root.children ?? []).map((s: Node) => (
            <g key={s.data.name}>
              <text
                x={s.x0 + 4}
                y={s.y0 + 12}
                fill={isDark ? "#e5e7eb" : "#111827"}
                fontSize={11}
                fontWeight={700}
                paintOrder="stroke"
                stroke={isDark ? "rgba(0,0,0,0.55)" : "rgba(255,255,255,0.65)"}
                strokeWidth={2}
              >
                {s.data.name}
                {s.data.sectorRet != null ? `  ${pct(s.data.sectorRet)}` : ""}
              </text>
              {(s.children ?? []).map((leaf: Node) => {
                const w = leaf.x1 - leaf.x0;
                const h = leaf.y1 - leaf.y0;
                const fs = Math.max(6, Math.min(15, Math.min(w / 3.2, h / 2.3)));
                const showTicker = w >= 22 && h >= 12;
                const showPct = w >= 34 && h >= 28;
                const isShort = leaf.data.weight < 0;
                const rgb = rgbFor(leaf.data.live_return, isDark);
                const ink = textInk(rgb);
                return (
                  <g key={`${s.data.name}-${leaf.data.figi}`}>
                    <rect
                      x={leaf.x0}
                      y={leaf.y0}
                      width={w}
                      height={h}
                      fill={`rgb(${rgb[0]},${rgb[1]},${rgb[2]})`}
                      // Shorts get a dashed amber border so a long and a short of equal SIZE are
                      // visually distinct (both are sized by |weight|).
                      stroke={isShort ? "rgba(245,158,11,0.95)" : "rgba(0,0,0,0.22)"}
                      strokeWidth={isShort ? 1.4 : 0.5}
                      strokeDasharray={isShort ? "3 2" : undefined}
                      onMouseEnter={() => setHover(leaf.data as CompositionHolding)}
                    />
                    {showTicker && (
                      <text
                        x={leaf.x0 + w / 2}
                        y={leaf.y0 + h / 2 - (showPct ? fs * 0.28 : 0)}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fill={ink.fill}
                        fontSize={fs}
                        fontWeight={600}
                        paintOrder="stroke"
                        stroke={ink.stroke}
                        strokeWidth={1.4}
                      >
                        {isShort ? "▼ " : ""}
                        {leaf.data.ticker ?? leaf.data.figi}
                      </text>
                    )}
                    {showPct && (
                      <text
                        x={leaf.x0 + w / 2}
                        y={leaf.y0 + h / 2 + fs * 0.85}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fill={ink.fill}
                        fontSize={fs * 0.82}
                        paintOrder="stroke"
                        stroke={ink.stroke}
                        strokeWidth={1.2}
                      >
                        {leaf.data.live_return == null ? wpct(leaf.data.weight) : pct(leaf.data.live_return)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      )}
      {hover && (
        <div
          className="pointer-events-none absolute z-10 w-72 rounded-lg border border-border bg-bg p-3 text-fg shadow-xl"
          style={{ left: Math.max(0, Math.min(pos.x + 14, (pos.w || 320) - 300)), top: pos.y + 14 }}
        >
          <div className="text-[11px] text-muted">
            {hover.sector}
            {hover.industry ? ` · ${hover.industry}` : ""}
          </div>
          <div className="mt-0.5 font-semibold">
            {hover.ticker ?? hover.figi} <span className="font-normal text-muted">· {hover.name ?? "—"}</span>
          </div>
          <div className="mt-1 flex items-baseline gap-2 text-sm">
            <span className="font-medium tabular-nums">
              {hover.weight < 0 ? "short " : ""}
              {wpct(hover.weight)} of book
            </span>
            <span
              className={
                hover.live_return == null
                  ? "text-muted"
                  : hover.live_return >= 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-600 dark:text-rose-400"
              }
            >
              {hover.live_return == null ? "—" : pct(hover.live_return)} ({hover.freshness})
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
