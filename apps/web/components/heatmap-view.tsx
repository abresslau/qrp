"use client";

import { hierarchy, treemap, treemapSquarify } from "d3-hierarchy";
import { useEffect, useMemo, useRef, useState } from "react";

type Cell = {
  ticker: string;
  name: string;
  sector: string;
  industry: string | null;
  market_cap_usd: number;
  market_cap_lcy: number | null;
  currency: string | null;
  price: number | null;
  ret: number | null;
  freshness?: string; // LIVE mode only (QH.9): live | delayed | unavailable
};
type Heatmap = {
  universe_id: string;
  universe_name: string;
  window: string;
  members_resolved: number;
  shown: number;
  missing_mcap: number;
  merged_share_classes: number;
  cells: Cell[];
  // LIVE mode only (QH.9):
  as_of?: string | null;
  freshness?: string;
  priced?: number;
  total?: number;
};

// LIVE (QH.9) sentinel for the window selector + the freshness badge styles (mirrors the
// analytics-panel FRESH_STYLE). EOD windows are unaffected.
const LIVE = "LIVE";
const LIVE_STYLE: Record<string, string> = {
  live: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  delayed: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  unavailable: "border-border bg-fg/5 text-muted",
};
type UniverseRef = { universe_id: string; name: string; members_resolved: number };
type WindowOpt = { code: string; label: string };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Node = any;

const W = 1000;
const H = 640;
const HEADER = 16;
const CLAMP = 0.03; // ±3% saturates the color scale (matches the legend)

// Perplexity-style diverging scale: red (neg) -> neutral (~0) -> green (pos); ±3% saturates.
// The neutral midpoint follows the theme (light neutral in light mode, dark in dark mode).
function rgbFor(ret: number | null, isDark: boolean): [number, number, number] {
  const mid = isDark ? [42, 42, 48] : [228, 228, 231];
  if (ret == null) return isDark ? [55, 55, 62] : [203, 205, 209]; // no return data
  const t = Math.max(-1, Math.min(1, ret / CLAMP));
  const neg = [224, 72, 90];
  const pos = [63, 174, 90];
  const tgt = t < 0 ? neg : pos;
  const u = Math.abs(t);
  const m = (a: number, b: number) => Math.round(a + (b - a) * u);
  return [m(mid[0], tgt[0]), m(mid[1], tgt[1]), m(mid[2], tgt[2])];
}

// Reactive dark-mode flag: observes the `.dark` class on <html> (set by the theme toggle).
function useIsDark(): boolean {
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

// Dark text on light tiles, white text on saturated/dark tiles — keeps labels readable.
function textInk([r, g, b]: [number, number, number]): { fill: string; stroke: string } {
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  return lum > 150
    ? { fill: "#111827", stroke: "rgba(255,255,255,0.35)" }
    : { fill: "#ffffff", stroke: "rgba(0,0,0,0.40)" };
}

function pct(r: number | null): string {
  return r == null ? "" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}

function fmtCap(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return v.toFixed(0);
}

function fmtPrice(v: number | null): string {
  return v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function HeatmapView({
  universes,
  windows,
  defaultUniverse,
  defaultWindow,
}: {
  universes: UniverseRef[];
  windows: WindowOpt[];
  defaultUniverse: string;
  defaultWindow: string;
}) {
  const [uni, setUni] = useState(defaultUniverse);
  const [win, setWin] = useState(defaultWindow);
  const [nonce, setNonce] = useState(0); // bump to re-fetch without changing uni/win (LIVE refresh)
  const [data, setData] = useState<Heatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Cell | null>(null);
  // Capture the container width alongside the cursor position when hovering, so the tooltip
  // clamp reads a state value (not containerRef.current) during render — refs must not be read
  // in render (react-hooks/refs).
  const [pos, setPos] = useState<{ x: number; y: number; w: number }>({ x: 0, y: 0, w: 0 });
  const isDark = useIsDark();

  useEffect(() => {
    let alive = true;
    // Reset + fetch inside an async IIFE: the setState calls live in the async flow, not the
    // synchronous effect body (react-hooks/set-state-in-effect).
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        // LIVE mode (QH.9) hits the live-recolor endpoint; an EOD window hits the window endpoint.
        const url =
          win === LIVE
            ? `/api/sym/universes/${uni}/heatmap/live`
            : `/api/sym/universes/${uni}/heatmap?window=${win}`;
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d: Heatmap = await r.json();
        if (alive) {
          setData(d);
          setLoading(false);
        }
      } catch (e) {
        if (alive) {
          setError(String(e));
          setLoading(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [uni, win, nonce]);

  const root = useMemo<Node>(() => {
    if (!data || data.cells.length === 0) return null;
    const groups: Record<string, Cell[]> = {};
    for (const c of data.cells) (groups[c.sector] ||= []).push(c);
    const sectors = Object.entries(groups).map(([name, cells]) => {
      let wsum = 0;
      let rsum = 0;
      for (const c of cells) {
        if (c.ret != null) {
          wsum += c.market_cap_usd;
          rsum += c.market_cap_usd * c.ret;
        }
      }
      return {
        name,
        sectorRet: wsum > 0 ? rsum / wsum : null,
        children: cells.map((c) => ({ ...c, value: c.market_cap_usd })),
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

  const selectCls =
    "rounded-md border border-border bg-surface px-2 py-1 text-fg outline-none focus:border-fg/40";

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold tracking-tight text-fg">
          {data?.universe_name ?? "Universe"} Heatmap
        </h1>
        <div className="flex items-center gap-2 text-sm">
          <select value={uni} onChange={(e) => setUni(e.target.value)} className={selectCls}>
            {universes.map((u) => (
              <option key={u.universe_id} value={u.universe_id}>
                {u.name}
              </option>
            ))}
          </select>
          <select value={win} onChange={(e) => setWin(e.target.value)} className={selectCls}>
            {windows.map((w) => (
              <option key={w.code} value={w.code}>
                {w.label}
              </option>
            ))}
            <option value={LIVE}>● LIVE</option>
          </select>
        </div>
      </div>

      {win === LIVE && !loading && data?.freshness && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`rounded px-1.5 py-0.5 font-medium uppercase ${LIVE_STYLE[data.freshness] ?? LIVE_STYLE.unavailable}`}
          >
            {data.freshness}
          </span>
          <span className="text-muted">
            {data.priced ?? 0}/{data.total ?? 0} priced
            {data.as_of ? ` · as of ${new Date(data.as_of).toLocaleTimeString()}` : ""} · not stored
          </span>
          <button
            type="button"
            onClick={() => setNonce((n) => n + 1)}
            className="ml-auto rounded-md border border-border px-2 py-0.5 text-muted hover:bg-fg/5 hover:text-fg"
          >
            ↻ refresh
          </button>
        </div>
      )}

      <div
        ref={containerRef}
        className="relative rounded-xl border border-border bg-surface p-2"
        onMouseMove={(e) => {
          const r = containerRef.current?.getBoundingClientRect();
          if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width });
        }}
        onMouseLeave={() => setHover(null)}
      >
        {error && (
          <div className="p-6 text-sm text-red-400">Failed to load heat map: {error}</div>
        )}
        {loading && !data && <div className="p-6 text-sm text-muted">Loading…</div>}
        {root && (
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="block w-full"
            role="img"
            aria-label="Universe heat map treemap"
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
                  const rgb = rgbFor(leaf.data.ret, isDark);
                  const ink = textInk(rgb);
                  return (
                    <g key={`${s.data.name}-${leaf.data.ticker}`}>
                      <rect
                        x={leaf.x0}
                        y={leaf.y0}
                        width={w}
                        height={h}
                        fill={`rgb(${rgb[0]},${rgb[1]},${rgb[2]})`}
                        stroke="rgba(0,0,0,0.22)"
                        strokeWidth={0.5}
                        onMouseEnter={() => setHover(leaf.data as Cell)}
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
                          {leaf.data.ticker}
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
                          {pct(leaf.data.ret)}
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
            style={{
              left: Math.min(pos.x + 14, (pos.w || 320) - 300),
              top: pos.y + 14,
            }}
          >
            <div className="text-[11px] text-muted">
              {hover.sector}
              {hover.industry ? ` · ${hover.industry}` : ""}
            </div>
            <div className="mt-0.5 font-semibold">
              {hover.ticker} <span className="font-normal text-muted">· {hover.name}</span>
            </div>
            <div className="mt-1 flex items-baseline gap-2 text-sm">
              <span className="font-medium tabular-nums">
                {hover.currency ?? ""} {fmtPrice(hover.price)}
              </span>
              <span
                className={
                  hover.ret == null
                    ? "text-muted"
                    : hover.ret >= 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-rose-600 dark:text-rose-400"
                }
              >
                {hover.ret == null ? "—" : pct(hover.ret)} ({data?.window})
              </span>
            </div>
            <div className="mt-1 text-xs tabular-nums text-muted">
              Market cap — USD ${fmtCap(hover.market_cap_usd)} · {hover.currency ?? "LCY"}{" "}
              {fmtCap(hover.market_cap_lcy)}
            </div>
            <div className="mt-2 border-t border-border pt-2">
              <div className="text-xs font-medium text-fg">News</div>
              <div className="text-xs text-muted">No news feed wired yet — placeholder.</div>
            </div>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-muted">
        <div className="flex items-center gap-2">
          <span>−3%</span>
          <span
            className="h-2 w-44 rounded"
            style={{
              background: `linear-gradient(to right, rgb(224,72,90), ${
                isDark ? "rgb(42,42,48)" : "rgb(228,228,231)"
              }, rgb(63,174,90))`,
            }}
          />
          <span>+3%</span>
        </div>
        {data && (
          <div>
            {data.shown} shown · sized by market cap · colored by {data.window} return
            {data.merged_share_classes
              ? ` · ${data.merged_share_classes} share classes merged`
              : ""}
            {data.missing_mcap ? ` · ${data.missing_mcap} hidden (no market cap)` : ""} · live
            from sym
          </div>
        )}
      </div>
    </div>
  );
}
