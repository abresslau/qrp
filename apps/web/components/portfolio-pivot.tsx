"use client";

import { useState } from "react";

import { type Composition, type CompositionHolding } from "@/components/portfolio-heatmap";
import { fmtCompact, fmtPrice } from "@/lib/format";

// A pivot-style grid: the book grouped by sector, each stock carrying the Explorer columns
// (country / exchange / ccy / price / volume / market cap) PLUS its weight, the trailing 1D/1M/3M/6M
// returns (re-based to the live price), and the Daily/MTD/YTD P&L contributions.
//
// P&L methodology (FX-hedged simplification): a position's P&L contribution = weight × return, taken
// in base currency with NO FX translation and NO coverage-normalisation, so contributions are additive
// and each P&L column totals to the portfolio's weighted window P&L. Daily P&L uses the LIVE return
// (so the grand total matches the page's Daily P&L panel exactly); MTD/YTD use their EOD windows.

function pct(r: number | null): string {
  return r == null || !Number.isFinite(r) ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function wpct(w: number | null): string {
  return w == null ? "—" : `${w >= 0 ? "" : "−"}${(Math.abs(w) * 100).toFixed(1)}%`;
}
function retClass(r: number | null): string {
  if (r == null || !Number.isFinite(r)) return "text-muted";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

// 52-week range bar: low — [track with a marker at the current price] — high. The marker sits at
// `pct` of the way from the 52w low to the 52w high (0 = at the low, 1 = at the high); its colour
// signals proximity (near-high green, near-low red, mid amber). Renders "—" when the API has no
// extremes row or a degenerate range. fmtPrice keeps the endpoint labels consistent with the Price column.
function RangeBar({
  low,
  high,
  pct: p,
  currency,
}: {
  low: number | null;
  high: number | null;
  pct: number | null;
  currency?: string | null;
}) {
  if (low == null || high == null || p == null || !Number.isFinite(p)) {
    return <span className="text-muted">—</span>;
  }
  const pos = Math.min(100, Math.max(0, p * 100));
  const tone = p >= 0.66 ? "bg-emerald-500" : p <= 0.34 ? "bg-rose-500" : "bg-amber-500";
  return (
    <div
      className="flex w-full items-center gap-1"
      title={`52-week ${fmtPrice(low, currency)} – ${fmtPrice(high, currency)} · ${pos.toFixed(0)}% of range`}
    >
      <span className="w-10 shrink-0 text-right tabular-nums text-[10px] text-muted">{fmtPrice(low, currency)}</span>
      <div className="relative h-1.5 min-w-[2rem] flex-1 rounded-full bg-fg/15">
        <div
          className={`absolute top-1/2 h-2.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm ${tone}`}
          style={{ left: `${pos}%` }}
        />
      </div>
      <span className="w-10 shrink-0 text-left tabular-nums text-[10px] text-muted">{fmtPrice(high, currency)}</span>
    </div>
  );
}

// Trailing return windows shown after Price — re-based to the live price by the API. `key` is the
// window_returns code; `label` is the column header. Order = column order.
const WINDOWS = [
  { key: "1D", label: "1D Chg" },
  { key: "1M", label: "1M Return" },
  { key: "3M", label: "3M Return" },
  { key: "6M", label: "6M Return" },
] as const;
// P&L contribution columns. "DAILY" uses the live return (matches the page's Daily P&L panel);
// "MTD"/"YTD" use those EOD windows off window_returns.
const PNL_COLS = [
  { label: "Daily P&L", win: "DAILY" },
  { label: "MTD P&L", win: "MTD" },
  { label: "YTD P&L", win: "YTD" },
] as const;

// --- column sorting (within each sector group) ----------------------------------------------
// The pivot stays grouped by sector (sectors ordered by gross weight); clicking a header sorts
// the holdings WITHIN each sector by that column. Numeric/range keys sort numerically, text keys
// lexicographically, and a null/missing value always sinks to the bottom regardless of direction.
type SortDir = "asc" | "desc";
type Sort = { key: string; dir: SortDir };

const PnlAccess = (h: CompositionHolding, win: string): number | null => {
  const r = win === "DAILY" ? h.live_return : (h.window_returns?.[win] ?? null);
  return r != null ? h.weight * r : null;
};

function sortValue(h: CompositionHolding, key: string): number | string | null {
  switch (key) {
    case "ticker": return h.ticker ?? h.figi;
    case "name": return h.name ?? null;
    case "country": return h.country ?? null;
    case "mic": return h.mic ?? null;
    case "currency": return h.currency ?? null;
    case "weight": return Math.abs(h.weight);
    case "price": return h.price;
    case "range": return h.range_pct;
    case "mcap": return h.market_cap_usd;
    case "volume": return h.volume;
    default:
      if (key.startsWith("ret:")) return h.window_returns?.[key.slice(4)] ?? null;
      if (key.startsWith("pnl:")) return PnlAccess(h, key.slice(4));
      return null;
  }
}

function compareByKey(a: CompositionHolding, b: CompositionHolding, sort: Sort): number {
  const va = sortValue(a, sort.key);
  const vb = sortValue(b, sort.key);
  if (va == null && vb == null) return 0;
  if (va == null) return 1; // nulls always last (per key)
  if (vb == null) return -1;
  const d =
    typeof va === "string" || typeof vb === "string"
      ? String(va).localeCompare(String(vb))
      : (va as number) - (vb as number);
  return sort.dir === "asc" ? d : -d;
}

// Ordered multi-key compare: first key decides, ties fall through to the next key, and so on
// (Array.sort is stable, so an all-equal row keeps its original relative position).
function compareHoldings(a: CompositionHolding, b: CompositionHolding, sorts: Sort[]): number {
  for (const s of sorts) {
    const d = compareByKey(a, b, s);
    if (d !== 0) return d;
  }
  return 0;
}

// A clickable column header. `align` mirrors the body cells (text→left, number→right, range→center);
// the default direction on first click is ascending for text, descending for numeric/range. Plain
// click = single sort on this column; Ctrl/Cmd-click adds it as a secondary sort (or toggles its
// direction if already active). When ≥2 columns sort, each active header shows its 1-based priority.
function SortableTh({
  label,
  sortKey,
  align,
  sorts,
  onSort,
}: {
  label: string;
  sortKey: string;
  align: "left" | "right" | "center";
  sorts: Sort[];
  onSort: (key: string, defaultDir: SortDir, additive: boolean) => void;
}) {
  const i = sorts.findIndex((s) => s.key === sortKey);
  const active = i >= 0;
  const dir = active ? sorts[i].dir : undefined;
  const alignCls = align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left";
  const justify = align === "right" ? "justify-end" : align === "center" ? "justify-center" : "justify-start";
  const defaultDir: SortDir = align === "left" ? "asc" : "desc";
  const arrow = active ? (dir === "asc" ? "▲" : "▼") : "";
  const priority = active && sorts.length > 1 ? String(i + 1) : ""; // shown only for multi-sort
  return (
    <th className={`px-2 py-1.5 font-medium ${alignCls}`} aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        title="Click to sort; Ctrl/Cmd-click to add a secondary sort"
        onClick={(e) => onSort(sortKey, defaultDir, e.ctrlKey || e.metaKey)}
        className={`flex w-full items-center gap-1 ${justify} hover:text-fg ${active ? "text-fg" : ""}`}
      >
        <span>{label}</span>
        <span className="text-[9px] leading-none tabular-nums">{arrow}{priority ? ` ${priority}` : ""}</span>
      </button>
    </th>
  );
}

export function PortfolioPivot({ data }: { data: Composition | null }) {
  // Ordered list of sort keys (index 0 = primary). Default = largest positions first (gross weight
  // desc), matching the book convention. Plain click sets a single sort; Ctrl/Cmd-click adds/toggles.
  const [sorts, setSorts] = useState<Sort[]>([{ key: "weight", dir: "desc" }]);
  const onSort = (key: string, defaultDir: SortDir, additive: boolean) =>
    setSorts((prev) => {
      const i = prev.findIndex((s) => s.key === key);
      if (additive) {
        // Ctrl/Cmd-click: toggle direction if already a sort key (keep its priority), else append.
        return i >= 0
          ? prev.map((s, j) => (j === i ? { key: s.key, dir: s.dir === "asc" ? "desc" : "asc" } : s))
          : [...prev, { key, dir: defaultDir }];
      }
      // Plain click: collapse to a single sort; toggle direction iff it's already the sole key.
      return prev.length === 1 && prev[0].key === key
        ? [{ key, dir: prev[0].dir === "asc" ? "desc" : "asc" }]
        : [{ key, dir: defaultDir }];
    });

  if (!data?.holdings?.length) {
    return <p className="text-sm text-muted">No holdings yet — upload a weight vector to see the breakdown.</p>;
  }

  // P&L contribution = weight × return (FX-hedged: base-currency, no FX translation, no normalisation).
  // Daily uses the live return; the other windows use the re-based trailing returns. Additive → the
  // sector subtotal and grand total are the plain Σ over the group; a missing return contributes nothing.
  const pnlOf = (h: CompositionHolding, win: string): number | null => {
    const r = win === "DAILY" ? h.live_return : (h.window_returns?.[win] ?? null);
    return r != null ? h.weight * r : null;
  };

  // Group by sector, sectors ordered by gross weight desc; holdings within each sector ordered by
  // the active column sort (default |weight| desc). Sorting reorders rows within their sector — the
  // sector grouping and subtotals are preserved.
  const bySector: Record<string, CompositionHolding[]> = {};
  for (const h of data.holdings) (bySector[h.sector] ||= []).push(h);
  const sectors = Object.entries(bySector)
    .map(([sector, rows]) => {
      const hs = rows.slice().sort((a, b) => compareHoldings(a, b, sorts));
      const wt = hs.reduce((s, h) => s + Math.abs(h.weight), 0);
      const pnls: Record<string, number> = {};
      for (const { win } of PNL_COLS) pnls[win] = hs.reduce((s, h) => s + (pnlOf(h, win) ?? 0), 0);
      return { sector, hs, wt, pnls };
    })
    .sort((a, b) => b.wt - a.wt);

  const totalPnls: Record<string, number> = {};
  for (const { win } of PNL_COLS) totalPnls[win] = sectors.reduce((s, x) => s + (x.pnls[win] ?? 0), 0);

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="w-full min-w-[72rem] text-xs">
        <thead className="border-b border-border bg-fg/5 text-left text-muted">
          <tr>
            {/* text columns left, numeric columns right, the 52-week range bar centered; every
                column is click-to-sort (sorts rows within each sector) */}
            <SortableTh label="Ticker" sortKey="ticker" align="left" sorts={sorts} onSort={onSort} />
            <SortableTh label="Name" sortKey="name" align="left" sorts={sorts} onSort={onSort} />
            <SortableTh label="Country" sortKey="country" align="left" sorts={sorts} onSort={onSort} />
            <SortableTh label="Exch" sortKey="mic" align="left" sorts={sorts} onSort={onSort} />
            <SortableTh label="Ccy" sortKey="currency" align="left" sorts={sorts} onSort={onSort} />
            <SortableTh label="Wt" sortKey="weight" align="right" sorts={sorts} onSort={onSort} />
            <SortableTh label="Price" sortKey="price" align="right" sorts={sorts} onSort={onSort} />
            {WINDOWS.map((w) => (
              <SortableTh key={w.key} label={w.label} sortKey={`ret:${w.key}`} align="right" sorts={sorts} onSort={onSort} />
            ))}
            <SortableTh label="52-week range" sortKey="range" align="center" sorts={sorts} onSort={onSort} />
            {PNL_COLS.map(({ label, win }) => (
              <SortableTh key={win} label={label} sortKey={`pnl:${win}`} align="right" sorts={sorts} onSort={onSort} />
            ))}
            <SortableTh label="Mkt cap" sortKey="mcap" align="right" sorts={sorts} onSort={onSort} />
            <SortableTh label="Volume" sortKey="volume" align="right" sorts={sorts} onSort={onSort} />
          </tr>
        </thead>
        <tbody>
          {/* Grand total pinned at the TOP of the grid (above the sector groups) so the book's
              weight + Daily/MTD/YTD P&L read first, before scrolling the per-name rows. */}
          <tr className="border-b-2 border-border bg-fg/5 font-semibold">
            <td className="px-2 py-1.5" colSpan={5}>
              Total · {data.n_holdings} holdings
            </td>
            <td className="px-2 py-1.5 text-right tabular-nums">{wpct(data.total_weight)}</td>
            {/* blank span over Price + 1D/1M/3M/6M + 52W Range (none aggregate) */}
            <td className="px-2 py-1.5" colSpan={6} />
            {PNL_COLS.map(({ win }) => (
              <td key={win} className={`px-2 py-1.5 text-right tabular-nums ${retClass(totalPnls[win])}`}>
                {pct(totalPnls[win])}
              </td>
            ))}
            {/* blank span over Mkt cap + Volume */}
            <td className="px-2 py-1.5" colSpan={2} />
          </tr>
          {sectors.map(({ sector, hs, wt, pnls }) => (
            <SectorGroup key={sector} sector={sector} hs={hs} wt={wt} pnls={pnls} gross={data.total_weight} pnlOf={pnlOf} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectorGroup({
  sector,
  hs,
  wt,
  pnls,
  gross,
  pnlOf,
}: {
  sector: string;
  hs: CompositionHolding[];
  wt: number;
  pnls: Record<string, number>;
  gross: number;
  pnlOf: (h: CompositionHolding, win: string) => number | null;
}) {
  return (
    <>
      {/* sector subtotal row (the pivot grouping) — sums WEIGHT and the P&L contributions only; the
          return windows are left blank (summing returns is meaningless). */}
      <tr className="border-y border-border bg-bg/40 text-[11px] uppercase tracking-wide text-muted">
        <td className="px-2 py-1 font-semibold text-fg" colSpan={5}>
          {sector} <span className="font-normal text-muted">· {hs.length}</span>
        </td>
        <td className="px-2 py-1 text-right font-semibold tabular-nums text-fg">
          {gross > 0 ? `${((wt / gross) * 100).toFixed(1)}%` : "—"}
        </td>
        {/* blank span over Price + 1D/1M/3M/6M + 52W Range */}
        <td colSpan={6} />
        {PNL_COLS.map(({ win }) => (
          <td key={win} className={`px-2 py-1 text-right font-semibold tabular-nums ${retClass(pnls[win])}`}>
            {pct(pnls[win])}
          </td>
        ))}
        {/* blank span over Mkt cap + Volume */}
        <td colSpan={2} />
      </tr>
      {hs.map((h) => (
        <tr key={h.figi} className="border-b border-border/50 hover:bg-fg/5">
          <td className="px-2 py-1 font-medium text-fg">{h.ticker ?? h.figi}</td>
          <td className="max-w-[16rem] truncate px-2 py-1 text-muted" title={h.name ?? ""}>{h.name ?? "—"}</td>
          <td className="px-2 py-1 text-muted">{h.country ?? "—"}</td>
          <td className="px-2 py-1 text-muted">{h.mic ?? "—"}</td>
          <td className="px-2 py-1 text-muted">{h.currency ?? "—"}</td>
          <td className="px-2 py-1 text-right tabular-nums text-fg">{wpct(h.weight)}</td>
          <td className="px-2 py-1 text-right tabular-nums text-fg">{fmtPrice(h.price, h.currency)}</td>
          {WINDOWS.map((w) => {
            const r = h.window_returns?.[w.key] ?? null;
            return (
              <td key={w.key} className={`px-2 py-1 text-right tabular-nums ${retClass(r)}`}>
                {pct(r)}
              </td>
            );
          })}
          <td className="px-2 py-1">
            <RangeBar low={h.low_52w} high={h.high_52w} pct={h.range_pct} currency={h.currency} />
          </td>
          {PNL_COLS.map(({ win }) => {
            const c = pnlOf(h, win);
            return (
              <td key={win} className={`px-2 py-1 text-right tabular-nums ${retClass(c)}`}>
                {pct(c)}
              </td>
            );
          })}
          <td className="px-2 py-1 text-right tabular-nums text-muted">{h.market_cap_usd == null ? "—" : `$${fmtCompact(h.market_cap_usd)}`}</td>
          <td className="px-2 py-1 text-right tabular-nums text-muted">{fmtCompact(h.volume)}</td>
        </tr>
      ))}
    </>
  );
}
