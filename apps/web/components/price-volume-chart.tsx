"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { axisTickCount, dateAxisTicks } from "@/lib/date-axis";
import { fmtCompact, fmtPrice } from "@/lib/format";

type Bar = {
  session_date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};
type ChartType = "line" | "area" | "candle";

type Range = { label: string; days: number; ytd?: boolean };
const RANGES: Range[] = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "YTD", days: 400, ytd: true }, // fetch a bit over a year, then clip to Jan-1 client-side
  { label: "1Y", days: 365 },
  { label: "2Y", days: 730 },
  { label: "3Y", days: 1095 },
  { label: "5Y", days: 1825 },
  { label: "10Y", days: 3650 },
];
const CHART_TYPES: ChartType[] = ["area", "candle", "line"];

// viewBox geometry (scales to container width). Price band on top, volume band below, a
// shared index-based x-axis. Hand-rolled SVG — consistent with the heatmap (no chart lib).
const W = 960;
const H = 340;
const PAD_L = 46;
const PAD_R = 12;
const PRICE_TOP = 12;
const PRICE_BOT = 224;
const VOL_TOP = 240;
const VOL_BOT = 318; // leaves ~22px for x labels

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

export function PriceVolumeChart({ figi, currency }: { figi: string; currency?: string | null }) {
  const isDark = useIsDark();
  const [rangeLabel, setRangeLabel] = useState("1Y");
  const [chartType, setChartType] = useState<ChartType>("area");
  const range = RANGES.find((r) => r.label === rangeLabel) ?? RANGES[4];
  const days = range.days;
  const [bars, setBars] = useState<Bar[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [pos, setPos] = useState<{ x: number; y: number; w: number }>({ x: 0, y: 0, w: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await fetch(`/api/sym/securities/${figi}/prices?days=${days}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d: Bar[] = await r.json();
        if (alive) {
          setBars(d);
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
  }, [figi, days]);

  // YTD is fetched as ~13 months then clipped client-side to Jan-1 of the latest bar's year
  // (the data's own calendar, not the wall clock — robust in the simulated-2026 env).
  const view = useMemo(() => {
    if (!bars || !range.ytd || bars.length === 0) return bars ?? [];
    const year = bars[bars.length - 1].session_date.slice(0, 4);
    return bars.filter((b) => b.session_date >= `${year}-01-01`);
  }, [bars, range.ytd]);

  // Only points with a close drive the x-scale; volume is independent.
  const pts = useMemo(() => view.filter((b) => b.close != null), [view]);
  const scale = useMemo(() => {
    // candle needs the high/low extremes in view; line/area only the close.
    const lows = pts.map((b) => (chartType === "candle" && b.low != null ? b.low : (b.close as number)));
    const highs = pts.map((b) => (chartType === "candle" && b.high != null ? b.high : (b.close as number)));
    const vols = view.map((b) => b.volume ?? 0);
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const pad = (max - min) * 0.06 || max * 0.06 || 1;
    return { min: min - pad, max: max + pad, maxV: Math.max(1, ...vols) };
  }, [pts, view, chartType]);

  const n = pts.length;
  const xFor = (i: number) => (n <= 1 ? PAD_L : PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R));
  const yPrice = (v: number) =>
    PRICE_BOT - ((v - scale.min) / (scale.max - scale.min || 1)) * (PRICE_BOT - PRICE_TOP);
  const yVol = (v: number) => VOL_BOT - (v / scale.maxV) * (VOL_BOT - VOL_TOP);

  const linePath = useMemo(() => {
    if (n === 0) return "";
    return pts.map((b, i) => `${i === 0 ? "M" : "L"}${xFor(i).toFixed(1)},${yPrice(b.close as number).toFixed(1)}`).join("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pts, scale]);
  // area = the line closed down to the price baseline.
  const areaPath = useMemo(() => {
    if (n === 0 || chartType !== "area") return "";
    return `${linePath}L${xFor(n - 1).toFixed(1)},${PRICE_BOT}L${xFor(0).toFixed(1)},${PRICE_BOT}Z`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linePath, n, chartType]);

  // overall direction tints the line + the area fill
  const up = n >= 2 && (pts[n - 1].close as number) >= (pts[0].close as number);
  const upC = isDark ? "#34d399" : "#059669";
  const downC = isDark ? "#fb7185" : "#e11d48";
  const line = up ? upC : downC;
  const grid = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
  const axis = isDark ? "#8a8a8a" : "#6b7280";
  const volFill = isDark ? "rgba(148,163,184,0.30)" : "rgba(100,116,139,0.28)";

  const priceTicks = useMemo(() => {
    const out: number[] = [];
    for (let k = 0; k <= 3; k++) out.push(scale.min + ((scale.max - scale.min) * k) / 3);
    return out;
  }, [scale]);
  // x-ticks via the shared date-axis (lib/date-axis): width-driven count, even round step phased
  // from the start, labelled in the step's unit. Index-scaled chart -> map each tick to its nearest
  // bar. (The render anchors the first/last labels by x-position so they don't clip.)
  const xLabels = useMemo(() => {
    if (n === 0) return [] as { i: number; label: string }[];
    if (n === 1) return [{ i: 0, label: pts[0].session_date.slice(2) }];
    const times = pts.map((b) => new Date(b.session_date).getTime());
    return dateAxisTicks(times[0], times[n - 1], axisTickCount(W - PAD_L - PAD_R)).map((tk) => {
      let idx = 0;
      let best = Infinity;
      for (let i = 0; i < times.length; i++) {
        const dd = Math.abs(times[i] - tk.t);
        if (dd < best) {
          best = dd;
          idx = i;
        }
      }
      return { i: idx, label: tk.label };
    });
  }, [pts, n]);

  const hover = hoverIdx != null && hoverIdx < n ? pts[hoverIdx] : null;

  function onMove(e: React.MouseEvent) {
    const r = containerRef.current?.getBoundingClientRect();
    if (!r) return;
    setPos({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width });
    if (n === 0) return;
    const vbX = ((e.clientX - r.left) / r.width) * W; // container px → viewBox x
    const i = Math.round(((vbX - PAD_L) / (W - PAD_L - PAD_R)) * (n - 1));
    setHoverIdx(Math.max(0, Math.min(n - 1, i)));
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => setRangeLabel(r.label)}
              className={`px-2.5 py-1 ${
                rangeLabel === r.label ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
          {CHART_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setChartType(t)}
              className={`px-2.5 py-1 capitalize ${
                chartType === t ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted">Price &amp; volume{currency ? ` · ${currency}` : ""}</span>
      </div>

      {error && (
        <div className="mb-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          Couldn&apos;t load prices: {error}
        </div>
      )}

      <div
        ref={containerRef}
        className="relative rounded-xl border border-border bg-surface p-2"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {loading && !bars && <div className="p-6 text-sm text-muted">Loading…</div>}
        {!loading && n === 0 && (
          <div className="p-6 text-sm text-muted">No price history for this security.</div>
        )}
        {n > 0 && (
          <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img" aria-label="Price and volume chart">
            {/* price grid + y labels */}
            {priceTicks.map((t, k) => (
              <g key={k}>
                <line x1={PAD_L} x2={W - PAD_R} y1={yPrice(t)} y2={yPrice(t)} stroke={grid} strokeWidth={1} />
                <text x={PAD_L - 6} y={yPrice(t) + 3} textAnchor="end" fontSize={10} fill={axis}>
                  {fmtPrice(t, currency)}
                </text>
              </g>
            ))}
            {/* volume bars — aligned to the closes-only x-scale (pts carry volume too) */}
            {pts.map((b, i) => {
              if (!b.volume) return null;
              const x = xFor(i);
              const bw = Math.max(0.5, (W - PAD_L - PAD_R) / Math.max(n, 1) - 0.5);
              return (
                <rect key={i} x={x - bw / 2} y={yVol(b.volume)} width={bw} height={VOL_BOT - yVol(b.volume)} fill={volFill} />
              );
            })}
            <line x1={PAD_L} x2={W - PAD_R} y1={VOL_BOT} y2={VOL_BOT} stroke={grid} strokeWidth={1} />
            {/* price: line / area / candle */}
            {chartType === "area" && (
              <path d={areaPath} fill={up ? upC : downC} fillOpacity={isDark ? 0.14 : 0.1} stroke="none" />
            )}
            {chartType !== "candle" && (
              <path d={linePath} fill="none" stroke={line} strokeWidth={1.6} strokeLinejoin="round" />
            )}
            {chartType === "candle" &&
              pts.map((b, i) => {
                if (b.open == null || b.high == null || b.low == null || b.close == null) return null;
                const x = xFor(i);
                const cu = b.close >= b.open;
                const col = cu ? upC : downC;
                const bw = Math.max(1, (W - PAD_L - PAD_R) / Math.max(n, 1) - 1);
                const yo = yPrice(b.open);
                const yc = yPrice(b.close);
                const top = Math.min(yo, yc);
                const bodyH = Math.max(1, Math.abs(yo - yc));
                return (
                  <g key={i}>
                    <line x1={x} x2={x} y1={yPrice(b.high)} y2={yPrice(b.low)} stroke={col} strokeWidth={0.8} />
                    <rect x={x - bw / 2} y={top} width={bw} height={bodyH} fill={col} />
                  </g>
                );
              })}
            {/* x labels */}
            {xLabels.map(({ i, label }) => {
              const x = xFor(i);
              const anchor = x < PAD_L + 24 ? "start" : x > W - PAD_R - 24 ? "end" : "middle";
              return (
                <text key={i} x={x} y={H - 6} textAnchor={anchor} fontSize={10} fill={axis}>
                  {label}
                </text>
              );
            })}
            {/* hover crosshair */}
            {hover && (
              <g>
                <line x1={xFor(hoverIdx as number)} x2={xFor(hoverIdx as number)} y1={PRICE_TOP} y2={VOL_BOT} stroke={axis} strokeWidth={0.7} strokeDasharray="3 3" />
                <circle cx={xFor(hoverIdx as number)} cy={yPrice(hover.close as number)} r={3} fill={line} />
              </g>
            )}
          </svg>
        )}

        {hover && (
          <div
            className="pointer-events-none absolute z-10 w-40 rounded-lg border border-border bg-bg/95 p-2.5 text-xs shadow-lg backdrop-blur"
            style={{ left: pos.x > pos.w - 170 ? pos.x - 160 : pos.x + 14, top: 8 }}
          >
            <div className="mb-1 font-medium text-fg">{hover.session_date}</div>
            {chartType === "candle" &&
              ([
                ["Open", hover.open],
                ["High", hover.high],
                ["Low", hover.low],
              ] as [string, number | null][]).map(([k, v]) => (
                <div key={k} className="flex justify-between tabular-nums">
                  <span className="text-muted">{k}</span>
                  <span className="text-fg">{fmtPrice(v, currency)}</span>
                </div>
              ))}
            <div className="flex justify-between tabular-nums">
              <span className="text-muted">Close</span>
              <span className="text-fg">{fmtPrice(hover.close, currency)}</span>
            </div>
            <div className="flex justify-between tabular-nums">
              <span className="text-muted">Volume</span>
              <span className="text-fg">{fmtCompact(hover.volume)}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
