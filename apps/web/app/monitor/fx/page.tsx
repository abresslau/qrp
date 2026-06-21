"use client";

// FX cross-rate matrix (Bloomberg-FXC style). Two grids, same layout: the cross RATE and its daily %
// CHANGE (green/red heat). Default orientation matches FXC — the COLUMN currency is the base, so a
// cell is units of the ROW currency per 1 COLUMN currency (USD-row/EUR-col = EUR/USD = 1.11). A
// "Base" control flips the base axis (columns ⟷ rows). Derived from QRP's USD-base fx_rate star
// (crosses computed, never stored); per-currency as-of staleness is marked. No vendor IP.

import { type CSSProperties, type DragEvent, useEffect, useMemo, useState, useSyncExternalStore } from "react";

type Cell = { rate: number | null; chg: number | null; stale: boolean; pair: string };
type Row = { base: string; cells: Cell[] };
type Meta = {
  currency: string;
  status: string;
  observed_date: string | null;
  days_stale: number;
  quote_rank: number;
};
type Matrix = { as_of_date: string; currencies: string[]; meta: Meta[]; rows: Row[] };
type BaseAxis = "columns" | "rows"; // which axis is the cross base (cell orientation)

// Pairs quoted in these (large-value) currencies read at 2 dp; everything else at 4 dp.
const TWO_DP_QUOTE = new Set(["JPY", "HUF", "KRW", "IDR", "CLP", "COP"]);

// Currency → ISO-3166 country code (EUR → the EU flag). Flags are bundled MIT flag-icons SVGs in
// public/flags (same-origin, no dependency) — emoji flags don't render on Windows, so we use images.
const CCY_CC: Record<string, string> = {
  USD: "us", EUR: "eu", GBP: "gb", JPY: "jp", CHF: "ch", CAD: "ca", AUD: "au", NZD: "nz",
  SEK: "se", NOK: "no", DKK: "dk", HKD: "hk", SGD: "sg", MXN: "mx", CNY: "cn", BRL: "br",
  THB: "th", CZK: "cz", HUF: "hu", IDR: "id", KRW: "kr", MYR: "my", TRY: "tr", INR: "in",
  ILS: "il", TWD: "tw", ZAR: "za",
};

function Flag({ ccy }: { ccy: string }) {
  const cc = CCY_CC[ccy];
  if (!cc) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- tiny static same-origin SVG, no Image opt needed
    <img
      src={`/flags/${cc}.svg`}
      alt=""
      aria-hidden
      width={15}
      height={11}
      className="inline-block h-[11px] w-[15px] rounded-[1px] align-middle ring-1 ring-border/50 2xl:h-[13px] 2xl:w-[18px]"
    />
  );
}

function fmtRate(rate: number | null, quote: string): string {
  if (rate == null || !Number.isFinite(rate)) return "—";
  const dp = TWO_DP_QUOTE.has(quote) ? 2 : 4;
  return rate.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function fmtChg(chg: number | null): string {
  if (chg == null || !Number.isFinite(chg)) return "—";
  return `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%`;
}

// Conditional formatting by the cross's day-on-day move, on the platform's diverging heat scale
// (red → neutral → green, shared with the portfolio/sym heat maps). Banded like a Bloomberg FXC heat
// map: neutral inside ±0.05%, then ±0.5% and ±2.5% step to deeper colour. FX daily moves are small.
const HEAT_NEG: [number, number, number] = [224, 72, 90]; // same red as portfolio-heatmap rgbFor
const HEAT_POS: [number, number, number] = [63, 174, 90]; // same green
const heatMid = (isDark: boolean): [number, number, number] => (isDark ? [42, 42, 48] : [228, 228, 231]);

// Intensity for the band a move falls in: 0 = neutral (no fill), then the three FXC bands.
function heatIntensity(chg: number | null): number {
  if (chg == null || !Number.isFinite(chg)) return 0;
  const m = Math.abs(chg);
  if (m < 0.0005) return 0; // ±0.05% → neutral
  if (m < 0.005) return 0.34; // 0.05%–0.5%
  if (m < 0.025) return 0.67; // 0.5%–2.5%
  return 1; // ≥ 2.5%
}
// Band colour: blend the neutral midpoint toward red/green by the band intensity. null = no fill.
function heatRgb(chg: number, isDark: boolean): [number, number, number] | null {
  const u = heatIntensity(chg);
  if (u === 0) return null;
  const mid = heatMid(isDark);
  const tgt = chg >= 0 ? HEAT_POS : HEAT_NEG;
  const mix = (a: number, b: number) => Math.round(a + (b - a) * u);
  return [mix(mid[0], tgt[0]), mix(mid[1], tgt[1]), mix(mid[2], tgt[2])];
}
// Ink colour for contrast on a filled cell (luminance threshold).
function heatInk([r, g, b]: [number, number, number]): string {
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#111827" : "#f8fafc";
}
function heatStyle(chg: number | null, isDark: boolean): CSSProperties | undefined {
  if (chg == null) return undefined;
  const rgb = heatRgb(chg, isDark);
  if (!rgb) return undefined;
  return { backgroundColor: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`, color: heatInk(rgb) };
}

// Tracks the active theme so the heat scale (and its neutral midpoint) follow light/dark.
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

// Bottom-of-page key for the conditional formatting, mirroring the FXC "% change on day" legend.
const HEAT_BANDS: { chg: number; label: string }[] = [
  { chg: -0.03, label: "≤ −2.5%" },
  { chg: -0.01, label: "−0.5 to −2.5%" },
  { chg: -0.002, label: "−0.05 to −0.5%" },
  { chg: 0, label: "±0.05%" },
  { chg: 0.002, label: "0.05 to 0.5%" },
  { chg: 0.01, label: "0.5 to 2.5%" },
  { chg: 0.03, label: "≥ 2.5%" },
];
function HeatLegend({ isDark }: { isDark: boolean }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[9px] text-muted 2xl:mt-3 2xl:gap-1.5 2xl:text-[10px]">
      <span className="mr-1 uppercase tracking-wide">% change on day</span>
      {HEAT_BANDS.map((b) => {
        const style = heatStyle(b.chg, isDark);
        return (
          <span
            key={b.label}
            className={`rounded px-1.5 py-0.5 ${style ? "" : "border border-border text-fg"}`}
            style={style}
          >
            {b.label}
          </span>
        );
      })}
    </div>
  );
}

function headerMarker(m: Meta | undefined) {
  if (!m || m.status === "ok") return null;
  const title =
    m.status === "stale" ? `stale — last observed ${m.observed_date} (${m.days_stale}d)` : "no data";
  return (
    <span className="ml-0.5 text-amber-500" title={title}>
      ●
    </span>
  );
}

// The manual currency order lives in localStorage and is read via useSyncExternalStore (like the
// sidebar/theme) — no set-state-in-effect, a stable server snapshot (empty = default order) so
// hydration never mismatches, and the snapshot is cached so a re-render only happens on real change.
const ORDER_KEY = "qrp.fx.order";
const EMPTY_ORDER: string[] = [];
const orderListeners = new Set<() => void>();
let orderCacheRaw: string | null = null;
let orderCacheVal: string[] = EMPTY_ORDER;
function subscribeOrder(cb: () => void): () => void {
  orderListeners.add(cb);
  window.addEventListener("storage", cb); // cross-tab
  return () => {
    orderListeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}
function getOrderSnapshot(): string[] {
  try {
    const raw = localStorage.getItem(ORDER_KEY);
    if (raw !== orderCacheRaw) {
      const parsed = raw ? (JSON.parse(raw) as string[]) : EMPTY_ORDER;
      orderCacheRaw = raw;
      orderCacheVal = Array.isArray(parsed) ? parsed : EMPTY_ORDER;
    }
    return orderCacheVal;
  } catch {
    return EMPTY_ORDER;
  }
}
function getOrderServerSnapshot(): string[] {
  return EMPTY_ORDER;
}
function setOrderStored(next: string[]): void {
  try {
    localStorage.setItem(ORDER_KEY, JSON.stringify(next));
    orderListeners.forEach((l) => l()); // notify this tab (the storage event is cross-tab only)
  } catch {
    /* storage unavailable — the order just won't persist */
  }
}
function clearOrderStored(): void {
  try {
    localStorage.removeItem(ORDER_KEY);
    orderListeners.forEach((l) => l());
  } catch {
    /* ignore */
  }
}

// Small localStorage-backed store for a single string preference, read via useSyncExternalStore
// (same contract as the order store): stable server snapshot = the fallback (no hydration mismatch),
// scalar snapshot so React only re-renders on a real change. Used for base currency / sorting / axis.
function makeStringStore(key: string, fallback: string) {
  const listeners = new Set<() => void>();
  return {
    subscribe(cb: () => void): () => void {
      listeners.add(cb);
      window.addEventListener("storage", cb); // cross-tab
      return () => {
        listeners.delete(cb);
        window.removeEventListener("storage", cb);
      };
    },
    getSnapshot(): string {
      try {
        return localStorage.getItem(key) ?? fallback;
      } catch {
        return fallback;
      }
    },
    getServerSnapshot(): string {
      return fallback;
    },
    set(value: string): void {
      try {
        localStorage.setItem(key, value);
        listeners.forEach((l) => l()); // notify this tab (storage event is cross-tab only)
      } catch {
        /* storage unavailable — the choice just won't persist */
      }
    },
  };
}
// Module-level (stable refs) so useSyncExternalStore doesn't resubscribe every render.
const baseCcyStore = makeStringStore("qrp.fx.baseCcy", "USD");
const sortingStore = makeStringStore("qrp.fx.sorting", "lf");
const baseAxisStore = makeStringStore("qrp.fx.baseAxis", "columns");

// One grid as its own card (title + its own column headers + matrix rows). Each card is an
// independent <table> using table-fixed + an identical <colgroup>, so the two cards' currency
// columns line up exactly even though they live in separate cards. `mode` picks rate vs % change.
function MatrixCard({
  mode,
  label,
  rowCurrencies,
  colCurrencies,
  baseAxis,
  cellOf,
  statusOf,
  isDark,
  dragCcy,
  setDragCcy,
  onReorder,
}: {
  mode: "rate" | "chg";
  label: string;
  rowCurrencies: string[];
  colCurrencies: string[];
  baseAxis: BaseAxis;
  cellOf: (base: string, quote: string) => Cell | undefined;
  statusOf: Map<string, Meta>;
  isDark: boolean;
  dragCcy: string | null;
  setDragCcy: (c: string | null) => void;
  onReorder: (from: string, to: string) => void;
}) {
  // identical min width on both cards (≥52px per currency col) → same column widths → aligned + scrolls
  const minWidth = colCurrencies.length * 52 + 80;
  // Drag a currency header to reorder; rows + columns share one order, so the other axis moves too.
  // The dragged currency travels in dataTransfer (browser-managed) so the drop reads it reliably
  // regardless of re-render timing; dragCcy state is just the visual (dimmed) cue.
  const dragProps = (ccy: string) => ({
    draggable: true,
    onDragStart: (e: DragEvent) => {
      setDragCcy(ccy);
      try {
        e.dataTransfer.setData("text/plain", ccy);
        e.dataTransfer.effectAllowed = "move";
      } catch {
        /* dataTransfer may be unavailable in some environments — dragCcy fallback covers it */
      }
    },
    onDragOver: (e: DragEvent) => e.preventDefault(), // mark every header a valid drop target
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      let from: string | null = null;
      try {
        from = e.dataTransfer.getData("text/plain") || null;
      } catch {
        from = null;
      }
      from = from || dragCcy;
      if (from && from !== ccy) onReorder(from, ccy);
      setDragCcy(null);
    },
    onDragEnd: () => setDragCcy(null),
    title: "Drag to reorder — rows and columns move together",
  });
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table
        className="w-full table-fixed text-[11px] leading-none [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap 2xl:text-xs 2xl:leading-tight"
        style={{ minWidth: `${minWidth}px` }}
      >
        <colgroup>
          <col className="w-11 2xl:w-14" />
          <col className="w-5 2xl:w-7" />
          {colCurrencies.map((c) => (
            <col key={c} />
          ))}
        </colgroup>
        <thead>
          <tr className="bg-fg/5">
            <th
              colSpan={colCurrencies.length + 2}
              className="border-b border-border/60 px-1.5 py-px text-left text-[10px] font-semibold uppercase tracking-wide text-muted 2xl:px-2 2xl:py-1 2xl:text-[11px]"
            >
              {label}
            </th>
          </tr>
          <tr className="border-b border-border">
            {/* corner spans the currency-code + flag columns; the cell ratio is row / column */}
            <th colSpan={2} className="px-1.5 py-0.5 text-left text-[9px] font-medium uppercase tracking-wide text-muted 2xl:px-2 2xl:py-1 2xl:text-[10px]">
              {baseAxis === "columns" ? "row / column" : "column / row"}
            </th>
            {colCurrencies.map((q) => (
              <th
                key={q}
                {...dragProps(q)}
                className={`cursor-move select-none px-1.5 py-px text-center font-semibold text-fg 2xl:px-2 2xl:py-1 ${
                  dragCcy === q ? "opacity-40" : ""
                }`}
              >
                <span className="inline-flex items-center justify-center gap-1">
                  <Flag ccy={q} />
                  <span>
                    {q}
                    {headerMarker(statusOf.get(q))}
                  </span>
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
      {rowCurrencies.map((rowCcy) => (
        <tr key={rowCcy} className="border-b border-border/30 hover:bg-fg/5">
          <th
            {...dragProps(rowCcy)}
            className={`cursor-move select-none px-1.5 py-px text-left font-semibold text-fg 2xl:px-2 2xl:py-1 ${
              dragCcy === rowCcy ? "opacity-40" : ""
            }`}
          >
            {rowCcy}
            {headerMarker(statusOf.get(rowCcy))}
          </th>
          <th className="py-px pr-1 text-center font-normal 2xl:py-1">
            <Flag ccy={rowCcy} />
          </th>
          {colCurrencies.map((colCcy) => {
            const diag = rowCcy === colCcy;
            // base axis sets the cross base: columns → cell is row per 1 column; rows → column per 1 row.
            const crossBase = baseAxis === "columns" ? colCcy : rowCcy;
            const quoteCcy = baseAxis === "columns" ? rowCcy : colCcy;
            const cell = cellOf(crossBase, quoteCcy);
            const value = cell?.rate ?? null;
            const chg = cell?.chg ?? null;
            const shown = mode === "rate" ? fmtRate(value, quoteCcy) : fmtChg(chg);
            const missing = mode === "rate" ? value == null : chg == null;
            // label the cell as base/quote (column/row) so the pair name matches the number shown —
            // e.g. USD-col / EUR-row = "USD/EUR 0.8725" (EUR per USD).
            const label = `${crossBase}/${quoteCcy}`;
            const title = diag
              ? undefined
              : missing
                ? `no fresh rate for ${label}`
                : `${label} ${fmtRate(value, quoteCcy)}${chg != null ? ` · ${fmtChg(chg)} 1d` : ""}`;
            // Heat fill (banded by the day's move) on both grids — rate and % change alike.
            const heat = !diag && !missing ? heatStyle(chg, isDark) : undefined;
            return (
              <td
                key={colCcy}
                className={[
                  "px-1.5 py-px text-center tabular-nums 2xl:px-2 2xl:py-1",
                  diag ? "bg-fg/5 text-muted" : missing ? "text-amber-500" : "text-fg",
                ].join(" ")}
                style={heat}
                title={title}
              >
                {diag ? "—" : shown}
                {cell?.stale && !missing ? <span className="ml-0.5 text-amber-500">●</span> : null}
              </td>
            );
          })}
        </tr>
      ))}
        </tbody>
      </table>
    </div>
  );
}

export default function FxMatrixPage() {
  const [data, setData] = useState<Matrix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string>(""); // "" = latest FX date; YYYY-MM-DD = backdated
  const [latestDate, setLatestDate] = useState<string>("");
  // Base currency / sorting / base axis — persisted to localStorage (like the column order) so a
  // refresh keeps the user's layout. first char of sorting = row, second = column ("f" 1st, "l" last).
  const baseCcy = useSyncExternalStore(baseCcyStore.subscribe, baseCcyStore.getSnapshot, baseCcyStore.getServerSnapshot);
  const sorting = useSyncExternalStore(sortingStore.subscribe, sortingStore.getSnapshot, sortingStore.getServerSnapshot) as "ff" | "fl" | "lf" | "ll";
  const baseAxis = useSyncExternalStore(baseAxisStore.subscribe, baseAxisStore.getSnapshot, baseAxisStore.getServerSnapshot) as BaseAxis;
  const isDark = useIsDark(); // heat scale follows the active theme
  // Manual currency order, shared by BOTH axes and persisted to localStorage. Empty = warehouse order.
  const order = useSyncExternalStore(subscribeOrder, getOrderSnapshot, getOrderServerSnapshot);
  const [dragCcy, setDragCcy] = useState<string | null>(null);

  // Re-fetch on as-of change; newest-wins guard. Capture the latest FX date on an un-backdated load
  // so the picker can default to (and be bounded by) it. Pure: state set only in async callbacks.
  useEffect(() => {
    let alive = true;
    const qs = asOf ? `?as_of_date=${encodeURIComponent(asOf)}` : "";
    fetch(`/api/sym/fx/matrix${qs}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`fx matrix -> ${r.status}`))))
      .then((d: Matrix) => {
        if (alive) {
          setData(d);
          setError(null);
          if (!asOf) setLatestDate(d.as_of_date ?? "");
        }
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [asOf]);

  const boardDate = data?.as_of_date ?? null;
  const backdated = asOf !== "" && asOf !== latestDate;
  const statusOf = useMemo(() => {
    const m = new Map<string, Meta>();
    for (const x of data?.meta ?? []) m.set(x.currency, x);
    return m;
  }, [data]);
  // cell lookup by (base, quote): the gateway stores rows keyed by base, cells in currency order.
  const cellOf = useMemo(() => {
    const idx = new Map((data?.currencies ?? []).map((c, i) => [c, i]));
    const byBase = new Map((data?.rows ?? []).map((r) => [r.base, r]));
    return (base: string, quote: string): Cell | undefined => {
      const qi = idx.get(quote);
      return qi == null ? undefined : byBase.get(base)?.cells[qi];
    };
  }, [data]);
  // Rows lead with the most important markets (the warehouse order is importance-ranked:
  // EUR, GBP, JPY, CHF, … with USD last → bottom row). Columns put USD first so the leftmost column
  // reads "X per USD" — the natural reference. (Important-first rows trade away a clean anti-diagonal.)
  // Place the base currency 1st or last on each axis (Sorting); the rest keep the warehouse importance
  // order. e.g. base=USD, row-last/col-first → USD bottom row + first column (the classic FX matrix).
  const all = useMemo(() => data?.currencies ?? [], [data]);
  const hasData = all.length > 0;

  // Effective base sequence, derived (no effect): the saved custom order reconciled against the
  // currencies actually present — keep saved sequence, drop departed, append any new — else warehouse.
  const sequence = useMemo(() => {
    if (!order.length || !all.length) return all;
    const present = new Set(all);
    const kept = order.filter((c) => present.has(c));
    if (!kept.length) return all;
    const added = all.filter((c) => !kept.includes(c));
    return [...kept, ...added];
  }, [order, all]);
  const customised = order.length > 0;

  // Drag a header to move a currency; persist. Both axes share `sequence`, so the other axis moves too.
  const reorder = (from: string, to: string) => {
    const fi = sequence.indexOf(from);
    const ti = sequence.indexOf(to);
    if (fi < 0 || ti < 0 || fi === ti) return;
    const next = [...sequence];
    next.splice(fi, 1);
    next.splice(ti, 0, from);
    setOrderStored(next); // persists + notifies the external store, which re-renders
  };
  const resetOrder = () => clearOrderStored();

  const base = sequence.includes(baseCcy) ? baseCcy : null;
  const placed = (atFirst: boolean) =>
    base
      ? atFirst
        ? [base, ...sequence.filter((c) => c !== base)]
        : [...sequence.filter((c) => c !== base), base]
      : sequence;
  const rowCurrencies = placed(sorting[0] === "f");
  const colCurrencies = placed(sorting[1] === "f");
  const baseOptions = all.includes("USD") ? ["USD", ...all.filter((c) => c !== "USD")] : all;

  return (
    <div className="w-full">
      <header className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 2xl:mb-3">
        <h1 className="text-base font-semibold text-fg 2xl:text-lg">FX cross-rate matrix</h1>
        <p className="grow text-xs text-muted">
          Cell = units of the <span className="text-fg">{baseAxis === "columns" ? "row" : "column"}</span>{" "}
          currency per 1 <span className="text-fg">{baseAxis === "columns" ? "column" : "row"}</span>{" "}
          (the {baseAxis === "columns" ? "column" : "row"} is the base).
        </p>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-muted" title="The reference currency to position on the axes">
            Base currency
            <span className="relative inline-flex items-center">
              <select
                value={baseCcy}
                onChange={(e) => baseCcyStore.set(e.target.value)}
                className="appearance-none rounded border border-border bg-bg py-0.5 pl-1.5 pr-5 text-xs text-fg"
              >
                {baseOptions.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <span aria-hidden className="pointer-events-none absolute right-1.5 text-[9px] text-muted">▾</span>
            </span>
          </label>
          <label className="flex items-center gap-1 text-xs text-muted" title="Where the base currency sits on each axis">
            Sorting
            <span className="relative inline-flex items-center">
              <select
                value={sorting}
                onChange={(e) => sortingStore.set(e.target.value)}
                className="appearance-none rounded border border-border bg-bg py-0.5 pl-1.5 pr-5 text-xs text-fg"
              >
                <option value="ff">Row · Base 1st / Column · Base 1st</option>
                <option value="fl">Row · Base 1st / Column · Base last</option>
                <option value="lf">Row · Base last / Column · Base 1st</option>
                <option value="ll">Row · Base last / Column · Base last</option>
              </select>
              <span aria-hidden className="pointer-events-none absolute right-1.5 text-[9px] text-muted">▾</span>
            </span>
          </label>
          <label className="flex items-center gap-1 text-xs text-muted" title="Which axis is the cross base (cell orientation)">
            Base axis
            <span className="relative inline-flex items-center">
              <select
                value={baseAxis}
                onChange={(e) => baseAxisStore.set(e.target.value)}
                className="appearance-none rounded border border-border bg-bg py-0.5 pl-1.5 pr-5 text-xs text-fg"
              >
                <option value="columns">columns</option>
                <option value="rows">rows</option>
              </select>
              <span aria-hidden className="pointer-events-none absolute right-1.5 text-[9px] text-muted">▾</span>
            </span>
          </label>
          {customised ? (
            <button
              type="button"
              onClick={resetOrder}
              className="rounded border border-border px-1.5 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg"
              title="Discard the saved drag order and return to the default ordering"
            >
              Reset order
            </button>
          ) : null}
          {boardDate ? (
            <span className="text-xs text-muted">
              EOD · as of {boardDate}
              {backdated ? " (backdated)" : ""}
            </span>
          ) : null}
          <label className="flex items-center gap-1 text-xs text-muted" title="Rewind the matrix to a past date">
            <span className="sr-only">As of date</span>
            <input
              type="date"
              value={asOf || latestDate}
              max={latestDate || undefined}
              onChange={(e) => setAsOf(e.target.value === latestDate ? "" : e.target.value)}
              className="rounded border border-border bg-bg px-1.5 py-0.5 text-xs text-fg"
            />
          </label>
          {backdated ? (
            <button
              type="button"
              onClick={() => setAsOf("")}
              className="rounded border border-border px-1.5 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg"
            >
              Latest
            </button>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-rose-500">
          Could not load the matrix: {error}
        </p>
      ) : data == null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : !hasData ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
          No FX data yet. Populate rates with <code className="rounded bg-fg/10 px-1">sym fx load</code>.
        </p>
      ) : (
        // Two separate cards (spot rate · % change). table-fixed + identical colgroup keeps the
        // currency columns aligned across both cards.
        <div className="space-y-1 2xl:space-y-3">
          <MatrixCard mode="rate" label="Spot rate" rowCurrencies={rowCurrencies} colCurrencies={colCurrencies} baseAxis={baseAxis} cellOf={cellOf} statusOf={statusOf} isDark={isDark} dragCcy={dragCcy} setDragCcy={setDragCcy} onReorder={reorder} />
          <MatrixCard mode="chg" label="Spot · daily % change" rowCurrencies={rowCurrencies} colCurrencies={colCurrencies} baseAxis={baseAxis} cellOf={cellOf} statusOf={statusOf} isDark={isDark} dragCcy={dragCcy} setDragCcy={setDragCcy} onReorder={reorder} />
          <HeatLegend isDark={isDark} />
        </div>
      )}

      <p className="mt-1.5 text-[10px] leading-snug text-muted 2xl:mt-3 2xl:text-[11px]">
        <span className="text-fg">Spot</span> (EOD) USD-base crosses (computed, not stored).{" "}
        <span className="text-fg">Drag any header</span> to reorder (both axes, saved); cells shaded by
        the day&apos;s move; <span className="text-amber-500">●</span> = stale/no rate. Hover for the pair.
      </p>
    </div>
  );
}
