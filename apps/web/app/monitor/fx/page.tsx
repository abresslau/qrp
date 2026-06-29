"use client";

// FX cross-rate matrix (Bloomberg-FXC style). Two grids, same layout: the cross RATE and its daily %
// CHANGE (green/red heat). Default orientation matches FXC — the COLUMN currency is the base, so a
// cell is units of the ROW currency per 1 COLUMN currency (USD-row/EUR-col = EUR/USD = 1.11). A
// "Base" control flips the base axis (columns ⟷ rows). Derived from QRP's USD-base fx_rate star
// (crosses computed, never stored); per-currency as-of staleness is marked. No vendor IP.

import { type CSSProperties, type DragEvent, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { useOnline } from "@/lib/connection";


type Cell = { rate: number | null; chg: number | null; stale: boolean; pair: string };
type Row = { base: string; cells: Cell[] };
type Meta = {
  currency: string;
  status: string;
  observed_date: string | null;
  days_stale: number;
  quote_rank: number;
  freshness?: string; // LIVE mode only: live | delayed | unavailable
  quote_time?: string | null;
};
// EOD has `as_of_date`; LIVE drops it and adds a freshness rollup (as_of / freshness / priced / total).
type Matrix = {
  as_of_date?: string;
  currencies: string[];
  meta: Meta[];
  rows: Row[];
  as_of?: string | null;
  freshness?: string;
  priced?: number;
  total?: number;
};
type LiveMeta = { as_of: string | null; freshness: string; priced: number; total: number };
type Mode = "EOD" | "LIVE";
type BaseAxis = "columns" | "rows"; // which axis is the cross base (cell orientation)

// LIVE-mode freshness → colour (mirrors the WEI board): live = fresh (no marker), delayed = amber,
// unavailable = muted. Used by the per-currency axis-header marker in LIVE mode.
const LIVE_TONE: Record<string, string> = {
  live: "text-emerald-500",
  delayed: "text-amber-500",
  unavailable: "text-muted",
};

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
      className="inline-block h-[11px] w-[15px] rounded-[1px] align-middle ring-1 ring-border/50"
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
    <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[9px] text-muted">
      <span className="mr-1 uppercase tracking-wide">% change on day</span>
      {HEAT_BANDS.map((b) => {
        const style = heatStyle(b.chg, isDark);
        return (
          <span
            key={b.label}
            className={`rounded px-2 py-0.5 ${style ? "" : "border border-border text-fg"}`}
            style={style}
          >
            {b.label}
          </span>
        );
      })}
    </div>
  );
}

function headerMarker(m: Meta | undefined, mode: Mode) {
  if (!m) return null;
  // LIVE: mark the per-currency quote freshness (live = no marker; delayed = amber; unavailable =
  // muted — showing the EOD rate). USD is the exact pivot and always reads "live" (no marker).
  if (mode === "LIVE") {
    const f = m.freshness;
    if (!f || f === "live") return null;
    const title =
      f === "unavailable"
        ? `no live quote — showing the EOD rate${m.observed_date ? ` (${m.observed_date})` : ""}`
        : `delayed quote${m.quote_time ? ` · as of ${new Date(m.quote_time).toLocaleTimeString()}` : ""}`;
    return (
      <span className={`ml-0.5 ${LIVE_TONE[f] ?? "text-muted"}`} title={title}>
        ●
      </span>
    );
  }
  // EOD: mark a carried-forward / withheld as-of resolution.
  if (m.status === "ok") return null;
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
  boardMode,
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
  boardMode: Mode;
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
        className="w-full table-fixed text-[11px] leading-tight [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap"
        style={{ minWidth: `${minWidth}px` }}
      >
        <colgroup>
          <col className="w-11" />
          <col className="w-5" />
          {colCurrencies.map((c) => (
            <col key={c} />
          ))}
        </colgroup>
        <thead>
          <tr className="bg-fg/5">
            <th
              colSpan={colCurrencies.length + 2}
              className="border-b border-border/60 px-2 py-0.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted"
            >
              {label}
            </th>
          </tr>
          <tr className="border-b border-border">
            {/* corner spans the currency-code + flag columns; the cell ratio is row / column */}
            <th colSpan={2} className="px-2 py-0.5 text-left text-[9px] font-medium uppercase tracking-wide text-muted">
              {baseAxis === "columns" ? "row / column" : "column / row"}
            </th>
            {colCurrencies.map((q) => (
              <th
                key={q}
                {...dragProps(q)}
                className={`cursor-move select-none px-2 py-0.5 text-center font-semibold text-fg ${
                  dragCcy === q ? "opacity-40" : ""
                }`}
              >
                <span className="inline-flex items-center justify-center gap-1">
                  <Flag ccy={q} />
                  <span>
                    {q}
                    {headerMarker(statusOf.get(q), boardMode)}
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
            className={`cursor-move select-none px-2 py-0.5 text-left font-semibold text-fg ${
              dragCcy === rowCcy ? "opacity-40" : ""
            }`}
          >
            {rowCcy}
            {headerMarker(statusOf.get(rowCcy), boardMode)}
          </th>
          <th className="py-0.5 pr-1 text-center font-normal">
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
                  "px-2 py-0.5 text-center tabular-nums",
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
  const [mode, setMode] = useState<Mode>("EOD"); // LIVE = intraday spot quotes (best-effort, not stored)
  const [live, setLive] = useState<LiveMeta | null>(null); // LIVE rollup (worst freshness + as_of + coverage)
  const [nonce, setNonce] = useState(0); // bump to force a LIVE re-fetch (↻ / auto-refresh tick)
  const [loading, setLoading] = useState(false);
  const [autoSec, setAutoSec] = useState(0); // LIVE auto-refresh interval in seconds; 0 = off
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null); // local clock of the last LIVE pull
  const online = useOnline(); // sidebar offline toggle pauses LIVE auto-refresh

  // Re-fetch on mode / as-of / refresh. Newest-wins via AbortController so a slow earlier load can't
  // clobber a newer one. EOD: an as-of date backdates the matrix (empty ⇒ latest; capture the latest FX
  // date for the picker bound). LIVE: fetch the live matrix (spot quotes re-marked onto the EOD legs) +
  // its freshness rollup; as-of is EOD-only (LIVE is "now"). Quotes are best-effort and never persisted.
  useEffect(() => {
    const ac = new AbortController();
    const url =
      mode === "LIVE"
        ? "/api/sym/fx/matrix/live"
        : `/api/sym/fx/matrix${asOf ? `?as_of_date=${encodeURIComponent(asOf)}` : ""}`;
    fetch(url, { cache: "no-store", signal: ac.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`fx matrix -> ${r.status}`))))
      .then((d: Matrix) => {
        // clear the refresh spinner on every settle (incl. a superseded/aborted request) so a rapid
        // toggle mid-refresh can't leave the ↻ button stuck disabled.
        setLoading(false);
        if (ac.signal.aborted) return;
        setData(d);
        setError(null);
        if (mode === "LIVE") {
          setLive({
            as_of: d.as_of ?? null,
            freshness: d.freshness ?? "unavailable",
            priced: d.priced ?? 0,
            total: d.total ?? 0,
          });
          // stamp the LOCAL clock each LIVE pull so an auto-refresh shows visible confirmation even
          // when the data's own `as_of` (sim-clock) doesn't move.
          setRefreshedAt(new Date().toLocaleTimeString());
        } else {
          setLive(null);
          if (!asOf) setLatestDate(d.as_of_date ?? "");
        }
      })
      .catch((e) => {
        setLoading(false);
        if (!ac.signal.aborted) setError(String(e));
      });
    return () => ac.abort();
  }, [mode, asOf, nonce]);

  // LIVE auto-refresh: while a positive interval is set, LIVE is selected, AND the app is online
  // (sidebar toggle), bump the refresh nonce on a timer (re-pulls via the effect above). setState lives
  // in the timer callback, not the effect body (react-hooks/set-state-in-effect). Floored at 3s to stay
  // polite; going offline / leaving LIVE clears the timer (deps). Mirrors the WEI board LIVE refresh.
  useEffect(() => {
    if (mode !== "LIVE" || autoSec <= 0 || !online) return;
    const id = setInterval(() => setNonce((n) => n + 1), Math.max(3, autoSec) * 1000);
    return () => clearInterval(id);
  }, [mode, autoSec, online]);

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
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <header className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h1 className="text-base font-semibold text-fg">FX cross-rate matrix</h1>
        <p className="grow text-xs text-muted">
          Cell = units of the <span className="text-fg">{baseAxis === "columns" ? "row" : "column"}</span>{" "}
          currency per 1 <span className="text-fg">{baseAxis === "columns" ? "column" : "row"}</span>{" "}
          (the {baseAxis === "columns" ? "column" : "row"} is the base).
        </p>
        <div className="flex items-center gap-2">
          {/* EOD ⟷ LIVE mode toggle (mirrors the WEI board) */}
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs" role="group" aria-label="matrix mode">
            {(["EOD", "LIVE"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={`px-2 py-0.5 ${mode === m ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
              >
                {m}
              </button>
            ))}
          </div>
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
              className="rounded border border-border px-2 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg"
              title="Discard the saved drag order and return to the default ordering"
            >
              Reset order
            </button>
          ) : null}
          {mode === "LIVE" ? (
            <>
              {live ? (
                <span
                  className={`text-xs ${LIVE_TONE[live.freshness] ?? "text-muted"}`}
                  title="Intraday spot quotes — best-effort, never stored"
                >
                  ● LIVE · {live.freshness} · {live.priced}/{live.total} priced
                  {live.as_of ? ` · as of ${new Date(live.as_of).toLocaleTimeString()}` : ""}
                  {refreshedAt ? ` · refreshed ${refreshedAt}` : ""}
                </span>
              ) : null}
              <label
                className="flex items-center gap-1 text-xs text-muted"
                title="Auto-refresh interval (seconds); blank or 0 = off. Floored at 3s. Pauses when offline."
              >
                auto
                <input
                  type="number"
                  min={0}
                  value={autoSec || ""}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setAutoSec(Number.isFinite(v) ? Math.max(0, Math.floor(v)) : 0);
                  }}
                  placeholder="off"
                  aria-label="Auto-refresh interval in seconds"
                  className="w-12 rounded border border-border bg-bg px-1 py-0.5 text-xs text-fg"
                />
                s{autoSec > 0 ? ` (${Math.max(3, autoSec)}s)` : ""}
              </label>
              <button
                type="button"
                onClick={() => {
                  setLoading(true);
                  setNonce((n) => n + 1);
                }}
                disabled={loading}
                aria-label="Refresh live quotes"
                className="rounded border border-border px-1.5 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg disabled:opacity-50"
              >
                {loading ? "…" : "↻"}
              </button>
            </>
          ) : (
            <>
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
                  className="rounded border border-border bg-bg px-2 py-0.5 text-xs text-fg"
                />
              </label>
              {backdated ? (
                <button
                  type="button"
                  onClick={() => setAsOf("")}
                  className="rounded border border-border px-2 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg"
                >
                  Latest
                </button>
              ) : null}
            </>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
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
          // Two cards (spot rate · % change) stacked, each filling the FULL WIDTH (w-full tables with a
          // per-currency min-width floor → they scroll horizontally only when the window is too narrow).
          // NOT wrapped in ScaleToFit: this board is taller than a laptop viewport, so a contain-fit would
          // shrink it to fit height and waste the width — instead it renders at full width and the page
          // scrolls to the % change grid. table-fixed + identical colgroup keeps the columns aligned.
          <div className="space-y-1">
            <MatrixCard mode="rate" boardMode={mode} label={mode === "LIVE" ? "Spot rate · LIVE" : "Spot rate"} rowCurrencies={rowCurrencies} colCurrencies={colCurrencies} baseAxis={baseAxis} cellOf={cellOf} statusOf={statusOf} isDark={isDark} dragCcy={dragCcy} setDragCcy={setDragCcy} onReorder={reorder} />
            <MatrixCard mode="chg" boardMode={mode} label={mode === "LIVE" ? "Spot · % change vs prior close" : "Spot · daily % change"} rowCurrencies={rowCurrencies} colCurrencies={colCurrencies} baseAxis={baseAxis} cellOf={cellOf} statusOf={statusOf} isDark={isDark} dragCcy={dragCcy} setDragCcy={setDragCcy} onReorder={reorder} />
            <HeatLegend isDark={isDark} />
          </div>
        )}
      </div>

      <p className="mt-1.5 shrink-0 text-[10px] leading-snug text-muted">
        {mode === "LIVE" ? (
          <>
            <span className="text-fg">LIVE</span> intraday spot crosses (USD-base legs re-marked to
            <code className="mx-0.5 rounded bg-fg/10 px-1">USD&lt;ccy&gt;=X</code> quotes, crosses
            re-derived) — best-effort, <strong>never stored</strong>; % change is vs the latest EOD close.{" "}
            <span className="text-amber-500">●</span> delayed / <span className="text-muted">●</span>{" "}
            unavailable (shows the EOD rate). FX trades nearly around the clock, so spot usually reads{" "}
            <em>live</em>; a quote behind the freshness threshold reads <em>delayed</em>.
          </>
        ) : (
          <>
            <span className="text-fg">Spot</span> (EOD) USD-base crosses (computed, not stored).{" "}
            <span className="text-fg">Drag any header</span> to reorder (both axes, saved); cells shaded
            by the day&apos;s move; <span className="text-amber-500">●</span> = stale/no rate. Hover for
            the pair.
          </>
        )}
      </p>
    </div>
  );
}
