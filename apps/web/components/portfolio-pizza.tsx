"use client";

import type { Composition } from "@/components/portfolio-heatmap";

// Categorical palette for the pizza slices — fixed order so colors are stable across renders, and
// chosen to read on both the light and dark surface. Cycles if there are more slices than colors.
const PALETTE = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899",
  "#14b8a6", "#f97316", "#6366f1", "#84cc16", "#06b6d4", "#a855f7",
  "#eab308", "#22c55e",
];
const OTHER_COLOR = "#9ca3af";
const POSITION_TOP_N = 12; // remaining holdings collapse into one "Other" slice

type Slice = { key: string; label: string; value: number; color: string };

function polar(cx: number, cy: number, r: number, ang: number): [number, number] {
  return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
}

// One donut segment path. Angles in radians, clockwise from -90° (top). A near-full segment is
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

function Donut({
  title,
  slices,
  centerTop,
  centerBottom,
}: {
  title: string;
  slices: Slice[];
  centerTop: string;
  centerBottom: string;
}) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  const S = 200;
  const cx = S / 2;
  const cy = S / 2;
  const R = 92;
  const r = 56;
  // Cumulative angles via a functional prefix sum (no post-render mutation; slice counts are tiny).
  const frac = (v: number) => (total > 0 ? v / total : 0);
  const arcs = slices.map((sl, i) => {
    const prior = slices.slice(0, i).reduce((s, x) => s + frac(x.value), 0);
    const a0 = -Math.PI / 2 + prior * Math.PI * 2;
    const a1 = a0 + frac(sl.value) * Math.PI * 2;
    return { sl, frac: frac(sl.value), d: donutArc(cx, cy, R, r, a0, a1) };
  });

  return (
    <div className="flex-1">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted">{title}</h3>
      <div className="mt-2 flex flex-wrap items-center gap-4">
        <svg
          viewBox={`0 0 ${S} ${S}`}
          className="h-44 w-44 shrink-0"
          role="img"
          aria-label={title}
        >
          {total > 0 ? (
            arcs.map((a) => <path key={a.sl.key} d={a.d} fill={a.sl.color} stroke="var(--bg, #fff)" strokeWidth={1} />)
          ) : (
            <circle cx={cx} cy={cy} r={R} fill="none" stroke="currentColor" className="text-border" strokeWidth={2} />
          )}
          <text x={cx} y={cy - 4} textAnchor="middle" className="fill-muted" fontSize={11}>
            {centerTop}
          </text>
          <text x={cx} y={cy + 13} textAnchor="middle" className="fill-fg" fontSize={15} fontWeight={700}>
            {centerBottom}
          </text>
        </svg>
        <ul className="min-w-[8rem] flex-1 space-y-1 text-xs">
          {arcs.map((a) => (
            <li key={a.sl.key} className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: a.sl.color }} />
              <span className="truncate text-fg" title={a.sl.label}>
                {a.sl.label}
              </span>
              <span className="ml-auto shrink-0 tabular-nums text-muted">{wpct(a.frac)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function PortfolioPizza({ data }: { data: Composition | null }) {
  if (!data?.holdings?.length || !data.sectors || !(data.total_weight > 0)) {
    return (
      <div className="rounded-xl border border-border bg-surface p-6 text-sm text-muted">
        No holdings to slice yet — upload a weight vector to see the sector / position breakdown.
      </div>
    );
  }

  // By sector: one slice per sector, sized by Σ|weight| (already aggregated server-side). The
  // legend shows ONE share% (slice ÷ chart total, computed in Donut) — for these charts the chart
  // total equals gross Σ|weight|, so share-of-chart and share-of-book are the same number; showing
  // it twice would be noise (review AC5 decision).
  const sectorSlices: Slice[] = data.sectors.map((s, i) => ({
    key: s.sector,
    label: s.sector,
    value: s.weight,
    color: PALETTE[i % PALETTE.length],
  }));

  // By position: one slice per holding sized by |weight|, top-N then an "Other" tail (holdings
  // arrive sorted by |weight| desc from the API).
  const sized = data.holdings.map((h) => ({ h, abs: Math.abs(h.weight) }));
  const top = sized.slice(0, POSITION_TOP_N);
  const rest = sized.slice(POSITION_TOP_N);
  const positionSlices: Slice[] = top.map((x, i) => ({
    key: x.h.figi,
    label: x.h.ticker ?? x.h.figi,
    value: x.abs,
    color: PALETTE[i % PALETTE.length],
  }));
  if (rest.length > 0) {
    const otherAbs = rest.reduce((s, x) => s + x.abs, 0);
    positionSlices.push({
      key: "__other__",
      label: `Other (${rest.length})`,
      value: otherAbs,
      color: OTHER_COLOR,
    });
  }

  const gross = wpct(data.total_weight);
  const net = `${data.net_weight >= 0 ? "" : "−"}${wpct(Math.abs(data.net_weight))}`;

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex flex-col gap-6 sm:flex-row">
        <Donut
          title="By sector (position size)"
          slices={sectorSlices}
          centerTop="gross"
          centerBottom={gross}
        />
        <Donut
          title="By position size"
          slices={positionSlices}
          centerTop={`${data.n_holdings} names · net`}
          centerBottom={net}
        />
      </div>
    </div>
  );
}
