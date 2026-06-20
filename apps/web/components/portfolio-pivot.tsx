"use client";

import { type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useRef, useState } from "react";

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

// --- column sorting -------------------------------------------------------------------------
// Clicking a header sorts the rows by that column — across the whole flat list, or WITHIN each
// group when the grid is grouped (groups ordered by gross weight desc). Numeric/range keys sort
// numerically, text keys lexicographically, and a null/missing value always sinks to the bottom
// regardless of direction.
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
    case "sector": return h.sector ?? null;
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
  onColPointerDown,
  dragging,
  dragOver,
  grouped,
  onClearGroup,
}: {
  label: string;
  sortKey: string;
  align: "left" | "right" | "center";
  sorts: Sort[];
  onSort: (key: string, defaultDir: SortDir, additive: boolean) => void;
  onColPointerDown: (e: ReactPointerEvent, id: string) => void;
  dragging: boolean;
  dragOver: boolean;
  grouped: boolean;
  onClearGroup: () => void;
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
    <th
      data-col-id={sortKey}
      onPointerDown={(e) => onColPointerDown(e, sortKey)}
      className={`cursor-grab select-none px-2 py-1.5 font-medium ${alignCls} ${dragging ? "opacity-40" : ""} ${dragOver ? "border-l-2 border-fg/70" : ""} ${grouped ? "bg-fg/10" : ""}`}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <div className="flex w-full items-center gap-1">
        <button
          type="button"
          title="Click to sort; Ctrl/Cmd-click to add a secondary sort; drag to reorder, or onto the drop strip to group"
          onClick={(e) => onSort(sortKey, defaultDir, e.ctrlKey || e.metaKey)}
          className={`flex flex-1 items-center gap-1 ${justify} hover:text-fg ${active ? "text-fg" : ""}`}
        >
        <span>{label}</span>
        <span className="text-[9px] leading-none tabular-nums">{arrow}{priority ? ` ${priority}` : ""}</span>
        </button>
        {grouped ? (
          <button
            type="button"
            aria-label="clear grouping"
            title={`Grouped by ${label} — click to ungroup`}
            onClick={(e) => {
              e.stopPropagation();
              onClearGroup();
            }}
            className="shrink-0 leading-none text-fg hover:text-rose-500"
          >
            ✕
          </button>
        ) : null}
      </div>
    </th>
  );
}

// --- column registry: one source of column identity + order, driving header + every body row -----
type ColAlign = "left" | "right" | "center";
type Column = { id: string; label: string; align: ColAlign; cell: (h: CompositionHolding) => ReactNode };

// `cell` returns the full <td> (keyed by id) so per-column classes + value coloring stay intact.
const COLUMNS: Column[] = [
  { id: "ticker", label: "Ticker", align: "left",
    cell: (h) => <td key="ticker" className="px-2 py-1 font-medium text-fg">{h.ticker ?? h.figi}</td> },
  { id: "name", label: "Name", align: "left",
    cell: (h) => <td key="name" className="max-w-[16rem] truncate px-2 py-1 text-muted" title={h.name ?? ""}>{h.name ?? "—"}</td> },
  { id: "country", label: "Country", align: "left",
    cell: (h) => <td key="country" className="px-2 py-1 text-muted">{h.country ?? "—"}</td> },
  { id: "mic", label: "Exch", align: "left",
    cell: (h) => <td key="mic" className="px-2 py-1 text-muted">{h.mic ?? "—"}</td> },
  { id: "currency", label: "Ccy", align: "left",
    cell: (h) => <td key="currency" className="px-2 py-1 text-muted">{h.currency ?? "—"}</td> },
  { id: "sector", label: "Sector", align: "left",
    cell: (h) => <td key="sector" className="max-w-[12rem] truncate px-2 py-1 text-muted" title={h.sector ?? ""}>{h.sector ?? "—"}</td> },
  { id: "weight", label: "Wt", align: "right",
    cell: (h) => <td key="weight" className="px-2 py-1 text-right tabular-nums text-fg">{wpct(h.weight)}</td> },
  { id: "price", label: "Price", align: "right",
    cell: (h) => <td key="price" className="px-2 py-1 text-right tabular-nums text-fg">{fmtPrice(h.price, h.currency)}</td> },
  ...WINDOWS.map((w): Column => ({
    id: `ret:${w.key}`, label: w.label, align: "right",
    cell: (h) => {
      const r = h.window_returns?.[w.key] ?? null;
      return <td key={`ret:${w.key}`} className={`px-2 py-1 text-right tabular-nums ${retClass(r)}`}>{pct(r)}</td>;
    },
  })),
  { id: "range", label: "52-week range", align: "center",
    cell: (h) => (
      <td key="range" className="px-2 py-1">
        <RangeBar low={h.low_52w} high={h.high_52w} pct={h.range_pct} currency={h.currency} />
      </td>
    ) },
  ...PNL_COLS.map(({ label, win }): Column => ({
    id: `pnl:${win}`, label, align: "right",
    cell: (h) => {
      const c = PnlAccess(h, win);
      return <td key={`pnl:${win}`} className={`px-2 py-1 text-right tabular-nums ${retClass(c)}`}>{pct(c)}</td>;
    },
  })),
  { id: "mcap", label: "Mkt cap", align: "right",
    cell: (h) => <td key="mcap" className="px-2 py-1 text-right tabular-nums text-muted">{h.market_cap_usd == null ? "—" : `$${fmtCompact(h.market_cap_usd)}`}</td> },
  { id: "volume", label: "Volume", align: "right",
    cell: (h) => <td key="volume" className="px-2 py-1 text-right tabular-nums text-muted">{fmtCompact(h.volume)}</td> },
];
const DEFAULT_COLUMN_ORDER = COLUMNS.map((c) => c.id);
const COLUMN_BY_ID: Record<string, Column> = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
// The aggregate rows (grand-total, sector subtotal) carry a value ONLY for weight + the P&L columns.
const isAggCol = (id: string) => id === "weight" || id.startsWith("pnl:");

// Per-column cell for the sector-subtotal row (weight % of the book + Σ P&L; blank otherwise).
function subtotalCell(id: string, wt: number, gross: number, pnls: Record<string, number>): ReactNode {
  if (id === "weight")
    return (
      <td key="weight" className="px-2 py-1 text-right font-semibold tabular-nums text-fg">
        {gross > 0 ? `${((wt / gross) * 100).toFixed(1)}%` : "—"}
      </td>
    );
  if (id.startsWith("pnl:")) {
    const v = pnls[id.slice(4)];
    return <td key={id} className={`px-2 py-1 text-right font-semibold tabular-nums ${retClass(v)}`}>{pct(v)}</td>;
  }
  return <td key={id} className="px-2 py-1" />;
}

// Per-column cell for the grand-total row (total book weight + Σ P&L; blank otherwise).
function totalCell(id: string, totalWeight: number, totalPnls: Record<string, number>): ReactNode {
  if (id === "weight")
    return <td key="weight" className="px-2 py-1.5 text-right tabular-nums">{wpct(totalWeight)}</td>;
  if (id.startsWith("pnl:")) {
    const v = totalPnls[id.slice(4)];
    return <td key={id} className={`px-2 py-1.5 text-right tabular-nums ${retClass(v)}`}>{pct(v)}</td>;
  }
  return <td key={id} className="px-2 py-1.5" />;
}

// The group/total label spans the leading non-aggregated columns; if an aggregated column was dragged
// to the front it falls back to a single leading cell (its aggregate value yields to the label there).
function labelSpan(order: string[]): number {
  const firstAgg = order.findIndex(isAggCol);
  return firstAgg > 0 ? firstAgg : 1;
}

export function PortfolioPivot({ data }: { data: Composition | null }) {
  // Ordered list of sort keys (index 0 = primary). Default = largest positions first (gross weight
  // desc), matching the book convention. Plain click sets a single sort; Ctrl/Cmd-click adds/toggles.
  const [sorts, setSorts] = useState<Sort[]>([{ key: "weight", dir: "desc" }]);
  // Set true while a column-drag is resolving so the trailing click doesn't also trigger a sort.
  const suppressClickRef = useRef(false);
  const onSort = (key: string, defaultDir: SortDir, additive: boolean) => {
    if (suppressClickRef.current) return;
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
  };

  // Column order (in-memory) + drag-to-reorder. `order` drives the header AND every body row, so they
  // can never diverge. We use Pointer Events (not the native HTML5 drag API, which doesn't reliably
  // start a drag from inside the header's <button>): press a header and move past a small threshold to
  // begin dragging; the column under the pointer is the drop target; releasing inserts the dragged
  // column before it. A drag suppresses the trailing click so it doesn't also sort.
  const [order, setOrder] = useState<string[]>(DEFAULT_COLUMN_ORDER);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  // Grouping: null = FLAT (default). A column id groups the rows by that column's value (a pivot).
  const [groupBy, setGroupBy] = useState<string | null>(null);
  const [dragOverZone, setDragOverZone] = useState(false); // header being dragged over the group-by zone
  const dragRef = useRef<{ id: string; startX: number; started: boolean } | null>(null);
  const dragCleanupRef = useRef<(() => void) | null>(null);

  const colUnder = (ev: PointerEvent): string | null => {
    const th = (ev.target as HTMLElement | null)?.closest?.("th[data-col-id]") as HTMLElement | null;
    return th?.dataset.colId ?? null;
  };
  const zoneUnder = (ev: PointerEvent): boolean =>
    !!(ev.target as HTMLElement | null)?.closest?.("[data-groupby-zone]");
  // Only categorical (text/left-aligned) columns make sensible group keys.
  const isGroupable = (id: string): boolean => COLUMN_BY_ID[id]?.align === "left";
  const onColPointerDown = (e: ReactPointerEvent, id: string) => {
    if (e.button > 0) return; // ignore right/middle button (left = 0; undefined in jsdom passes)
    dragRef.current = { id, startX: e.clientX, started: false };
    function teardown() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      dragCleanupRef.current = null;
      dragRef.current = null;
      setDraggingId(null);
      setDragOverId(null);
      setDragOverZone(false);
    }
    function onMove(ev: PointerEvent) {
      const st = dragRef.current;
      if (!st) return;
      if (!st.started) {
        if (Math.abs(ev.clientX - st.startX) < 5) return; // movement threshold separates click from drag
        st.started = true;
        setDraggingId(st.id);
      }
      ev.preventDefault();
      setDragOverZone(zoneUnder(ev));
      setDragOverId(zoneUnder(ev) ? null : colUnder(ev));
    }
    function onUp(ev: PointerEvent) {
      const st = dragRef.current;
      const targetId = colUnder(ev);
      const overZone = zoneUnder(ev);
      teardown();
      if (!st || !st.started) return; // it was a click, not a drag → let the sort handler run
      const swallowClick = () => {
        suppressClickRef.current = true; // a real drag happened → swallow the trailing click
        window.setTimeout(() => {
          suppressClickRef.current = false;
        }, 0);
      };
      if (overZone) {
        // Dropped on the group-by zone → group by this column (no-op for non-categorical columns).
        if (isGroupable(st.id)) {
          swallowClick();
          setGroupBy(st.id);
        }
        return; // a zone drop never reorders
      }
      if (!targetId || targetId === st.id) return;
      swallowClick();
      setOrder((prev) => {
        const next = prev.filter((x) => x !== st.id);
        const ti = next.indexOf(targetId);
        if (ti < 0) return prev;
        next.splice(ti, 0, st.id); // insert before the drop target
        return next;
      });
    }
    function onCancel() {
      teardown(); // OS/browser stole the gesture → drop the drag cleanly, no reorder
    }
    dragCleanupRef.current = teardown; // so an unmount mid-drag can tear the listeners down
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
  };
  // If the component unmounts mid-drag (e.g. a composition refetch swaps the tree), remove the
  // window listeners so they don't leak or fire setState on an unmounted component.
  useEffect(() => () => dragCleanupRef.current?.(), []);

  if (!data?.holdings?.length) {
    return <p className="text-sm text-muted">No holdings yet — upload a weight vector to see the breakdown.</p>;
  }

  // P&L contribution = weight × return (FX-hedged: base-currency, no FX translation, no normalisation).
  // Daily uses the live return; the other windows use the re-based trailing returns. Additive → the
  // sector subtotal and grand total are the plain Σ over the group; a missing return contributes nothing.
  // (Uses the module-level `PnlAccess` — the single source of the formula, shared with the cell renderers.)

  // FLAT by default; if `groupBy` is set, group rows by that column's value (a pivot), groups ordered
  // by gross weight desc, holdings within each group by the active sort. Grouping by `sector`
  // reproduces the original sector view. The group key reuses `sortValue` (the per-column accessor).
  const sortedFlat = data.holdings.slice().sort((a, b) => compareHoldings(a, b, sorts));
  const groups = groupBy
    ? Object.entries(
        data.holdings.reduce<Record<string, CompositionHolding[]>>((acc, h) => {
          const k = String(sortValue(h, groupBy) ?? "—");
          (acc[k] ||= []).push(h);
          return acc;
        }, {}),
      )
        .map(([label, rows]) => {
          const hs = rows.slice().sort((a, b) => compareHoldings(a, b, sorts));
          const wt = hs.reduce((s, h) => s + Math.abs(h.weight), 0);
          const pnls: Record<string, number> = {};
          for (const { win } of PNL_COLS) pnls[win] = hs.reduce((s, h) => s + (PnlAccess(h, win) ?? 0), 0);
          return { label, hs, wt, pnls };
        })
        .sort((a, b) => b.wt - a.wt)
    : null;

  const totalPnls: Record<string, number> = {};
  for (const { win } of PNL_COLS) {
    totalPnls[win] = data.holdings.reduce((s, h) => s + (PnlAccess(h, win) ?? 0), 0);
  }

  return (
    <div className="relative rounded-xl border border-border bg-surface">
      {/* Group-by zone: a floating overlay shown ONLY while a groupable column header is being dragged
          (no resting row, no reflow). Anchored just ABOVE the card (bottom-full) so it never pushes the
          table down or covers the header row — drag a header UP onto it to group; drop on another header
          to reorder. The grouped column's header carries an ✕ to ungroup. */}
      {draggingId && isGroupable(draggingId) ? (
        <div
          data-groupby-zone
          className={`absolute bottom-full left-0 right-0 z-20 mb-1 flex items-center justify-center gap-2 rounded-lg border border-dashed px-3 py-2 text-xs shadow-lg ${dragOverZone ? "border-fg/60 bg-fg/10 text-fg" : "border-border bg-surface text-muted"}`}
        >
          ⤓ Drop here to group by {COLUMN_BY_ID[draggingId]?.label ?? draggingId}
        </div>
      ) : null}
      <div className="overflow-x-auto">
      <table className="w-full min-w-[72rem] text-xs [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
        <thead className="border-b border-border bg-fg/5 text-left text-muted">
          <tr>
            {/* Columns are rendered in `order` (drag a header to reorder). Each is click-to-sort
                (orders the flat list, or rows within each group when grouped) and draggable.
                Alignment: text left, numeric right, 52-week range centered. */}
            {order.map((id) => {
              const col = COLUMN_BY_ID[id];
              if (!col) return null; // defensive: a stale order id would otherwise crash the table
              return (
                <SortableTh
                  key={id}
                  label={col.label}
                  sortKey={col.id}
                  align={col.align}
                  sorts={sorts}
                  onSort={onSort}
                  onColPointerDown={onColPointerDown}
                  dragging={draggingId === id}
                  dragOver={dragOverId === id}
                  grouped={groupBy === id}
                  onClearGroup={() => setGroupBy(null)}
                />
              );
            })}
          </tr>
        </thead>
        <tbody>
          {/* Grand total pinned at the TOP of the grid (above the sector groups) so the book's
              weight + Daily/MTD/YTD P&L read first, before scrolling the per-name rows. */}
          <tr className="border-b-2 border-border bg-fg/5 font-semibold">
            <td className="px-2 py-1.5" colSpan={labelSpan(order)}>
              Total · {data.n_holdings} holdings
            </td>
            {order.slice(labelSpan(order)).map((id) => totalCell(id, data.total_weight, totalPnls))}
          </tr>
          {groups
            ? groups.map(({ label, hs, wt, pnls }) => (
                <RowGroup key={label} label={label} hs={hs} wt={wt} pnls={pnls} gross={data.total_weight} order={order} />
              ))
            : /* FLAT (ungrouped): the holdings directly, sorted by the active sort, no group rows. */
              sortedFlat.map((h) => (
                <tr key={h.figi} className="border-b border-border/50 hover:bg-fg/5">
                  {order.map((id) => COLUMN_BY_ID[id]?.cell(h) ?? null)}
                </tr>
              ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function RowGroup({
  label,
  hs,
  wt,
  pnls,
  gross,
  order,
}: {
  label: string;
  hs: CompositionHolding[];
  wt: number;
  pnls: Record<string, number>;
  gross: number;
  order: string[];
}) {
  const span = labelSpan(order);
  return (
    <>
      {/* group subtotal row (the pivot grouping) — sums WEIGHT and the P&L contributions only; the
          return windows are left blank (summing returns is meaningless). Per-column cells follow the
          live column order; the label spans the leading non-aggregated columns. */}
      <tr className="border-y border-border bg-bg/40 text-[11px] uppercase tracking-wide text-muted">
        <td className="px-2 py-1 font-semibold text-fg" colSpan={span}>
          {label} <span className="font-normal text-muted">· {hs.length}</span>
        </td>
        {order.slice(span).map((id) => subtotalCell(id, wt, gross, pnls))}
      </tr>
      {hs.map((h) => (
        <tr key={h.figi} className="border-b border-border/50 hover:bg-fg/5">
          {order.map((id) => COLUMN_BY_ID[id]?.cell(h) ?? null)}
        </tr>
      ))}
    </>
  );
}
