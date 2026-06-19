"use client";

import { type MouseEvent as ReactMouseEvent, useEffect, useMemo, useState } from "react";

import { COMPARISON_CATEGORIES, MacroCompare } from "@/components/macro-compare";
import type { Schemas } from "@/lib/api";

type SeriesSummary = Schemas["SeriesSummary"];
type SeriesDetail = Schemas["SeriesDetail"];

// --- presentation helpers ----------------------------------------------------------------

const SOURCE_LABEL: Record<string, string> = {
  bcb: "BCB",
  bcb_focus: "BCB Focus",
  ibge: "IBGE",
  treasury: "US Treasury",
  fiscaldata: "US Treasury",
  worldbank: "World Bank",
  oecd: "OECD",
  ecb: "ECB",
  eurostat: "Eurostat",
};

// Sell-side section order + display titles for the macro buckets.
const CATEGORY_TITLE: Record<string, string> = {
  activity: "Activity",
  gdp: "GDP",
  inflation: "Inflation",
  employment: "Labour",
  rates: "Rates & Monetary",
  fx: "FX",
  fiscal: "Fiscal",
  debt: "Debt",
  external: "External",
  money: "Money & Credit",
  trade: "Trade",
  population: "Population",
};
const CATEGORY_ORDER = Object.keys(CATEGORY_TITLE);

// Headline indicators for the dashboard cockpit (landing only), grouped like a desk's
// front page: Brazil on top, the global/markets cross-asset read below.
const DASHBOARD_GROUPS: { title: string; ids: string[] }[] = [
  {
    title: "Brazil",
    ids: [
      "BCB:SELIC_TARGET",
      "BCB:IPCA_12M",
      "BCB:FOCUS_IPCA_12M",
      "BCB:BRLUSD",
      "IBGE:UNEMP",
      "BCB:IBCBR_SA",
      "BCB:DBGG",
      "BCB:CURRENT_ACCOUNT",
    ],
  },
  {
    title: "Global & markets",
    ids: [
      "UST:PAR_YIELD:10Y",
      "UST:PAR_YIELD:2Y",
      "BLS:UNRATE",
      "MKT:BRENT",
      "MKT:GOLD",
      "MKT:SPX",
      "MKT:IBOV",
      "MKT:DXY",
    ],
  },
];

// Series that read better together — a realised series and its market expectation overlaid
// on one axis (the sell-side "actual vs Focus" inflation chart). Symmetric.
const OVERLAY: Record<string, string> = {
  "BCB:IPCA_12M": "BCB:FOCUS_IPCA_12M",
  "BCB:FOCUS_IPCA_12M": "BCB:IPCA_12M",
};

function sourceLabel(s: string): string {
  return SOURCE_LABEL[s] ?? s;
}

function fmtNum(v: number | null | undefined, unit?: string | null): string {
  if (v == null) return "—";
  const pct = unit?.includes("%");
  const a = Math.abs(v);
  const s =
    a >= 1000
      ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
      : a >= 100
        ? v.toFixed(1)
        : v.toFixed(2);
  return pct ? `${s}%` : s;
}

function fmtDelta(v: number | null | undefined): string {
  if (v == null) return "—";
  const dp = Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2;
  return `${v > 0 ? "+" : ""}${v.toFixed(dp)}`;
}

// 12-month % change (unit-independent, so it ranks mixed-unit series fairly). null when
// there's no comparison point or a zero base.
function pct12m(s: SeriesSummary): number | null {
  if (s.latest == null || s.chg_12m == null) return null;
  const prior = s.latest - s.chg_12m;
  return prior ? (s.chg_12m / prior) * 100 : null;
}

function deltaClass(v: number | null | undefined): string {
  if (v == null) return "text-muted";
  if (v > 0) return "text-emerald-600 dark:text-emerald-400";
  if (v < 0) return "text-rose-600 dark:text-rose-400";
  return "text-muted";
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function fmtMonthYear(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

// Frequency-aware staleness so naturally-lagging series (annual WB, quarterly PIB) aren't
// falsely flagged — only data well past its expected refresh cadence reads as stale.
const _STALE_DAYS: Record<string, number> = { daily: 21, monthly: 80, quarterly: 250 };
function isStale(endDate?: string | null, freq?: string | null): boolean {
  if (!endDate) return true;
  const days = (Date.now() - Date.parse(endDate)) / 86_400_000;
  return days > (_STALE_DAYS[freq ?? ""] ?? 800); // default (annual) = ~26 months
}

const RANGES = { "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10, Max: null } as const;
type RangeKey = keyof typeof RANGES;

/** Download a series' FULL observation history as CSV (date,value) — the analyst's
 *  export-to-Excel path. Builds a Blob client-side; no server round trip. */
function downloadCsv(detail: SeriesDetail): void {
  const header = `# ${detail.name} — ${detail.geo ?? ""} (${detail.unit ?? ""}); source ${detail.source}`;
  const lines = [header, "date,value", ...detail.observations.map((o) => `${o.obs_date},${o.value}`)];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${detail.series_id.replace(/[^A-Za-z0-9]+/g, "_")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Slice a detail to the last N years (anchored to the series' OWN last obs, since end
 *  dates differ). Falls back to the full series if the window leaves < 2 points (e.g. an
 *  annual series over 1Y) so the chart never goes blank. */
function sliceByRange(detail: SeriesDetail, range: RangeKey): SeriesDetail {
  const years = RANGES[range];
  const obs = detail.observations;
  if (years == null || obs.length === 0) return detail;
  const cutoff = new Date(obs[obs.length - 1].obs_date);
  cutoff.setFullYear(cutoff.getFullYear() - years);
  const sliced = obs.filter((o) => new Date(o.obs_date) >= cutoff);
  return sliced.length >= 2 ? { ...detail, observations: sliced } : detail;
}

// --- tiny sparkline (table + cards) ------------------------------------------------------

function Sparkline({ values, className = "" }: { values: number[]; className?: string }) {
  const W = 120;
  const H = 28;
  if (!values || values.length < 2) return <span className="text-xs text-muted">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = W / (values.length - 1);
  const pts = values
    .map((v, i) => `${(i * step).toFixed(1)},${(H - 2 - ((v - min) / span) * (H - 4)).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={`h-7 w-[120px] ${up ? "text-emerald-500" : "text-rose-500"} ${className}`}
    >
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.4} />
    </svg>
  );
}

// --- featured research chart -------------------------------------------------------------

function FeaturedChart({
  detail,
  overlay,
}: {
  detail: SeriesDetail;
  overlay?: SeriesDetail | null;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const pts = detail.observations;
  const geom = useMemo(() => {
    const opts = overlay?.observations ?? [];
    if (pts.length < 2) return null;
    const W = 760;
    const H = 300;
    const padL = 48;
    const padR = 16;
    const padT = 16;
    const padB = 26;
    const allPts = [...pts, ...opts];
    const xs = pts.map((p) => new Date(p.obs_date).getTime());
    const allX = allPts.map((p) => new Date(p.obs_date).getTime());
    const ys = allPts.map((p) => p.value);
    const minX = Math.min(...allX);
    const maxX = Math.max(...allX);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const sx = (t: number) => padL + ((t - minX) / spanX) * (W - padL - padR);
    const sy = (v: number) => H - padB - ((v - minY) / spanY) * (H - padT - padB);
    const toLine = (arr: typeof pts) =>
      arr
        .map(
          (p, i) =>
            `${i ? "L" : "M"}${sx(new Date(p.obs_date).getTime()).toFixed(1)},${sy(p.value).toFixed(1)}`
        )
        .join(" ");
    const line = toLine(pts);
    const area = `${line} L${sx(xs[xs.length - 1]).toFixed(1)},${(H - padB).toFixed(1)} L${sx(xs[0]).toFixed(1)},${(H - padB).toFixed(1)} Z`;
    const overlayLine = opts.length >= 2 ? toLine(opts) : "";
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const v = minY + f * spanY;
      return { y: sy(v), v };
    });
    const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const t = minX + f * spanX;
      return { x: sx(t), label: new Date(t).getFullYear().toString() };
    });
    const last = pts[pts.length - 1];
    return {
      W, H, padR, padT, padB, line, area, overlayLine, yTicks, xTicks,
      zeroY: minY < 0 && maxY > 0 ? sy(0) : null,  // baseline for series that cross zero
      points: pts.map((p, i) => ({ x: sx(xs[i]), y: sy(p.value), v: p.value, d: p.obs_date })),
      lastX: sx(xs[xs.length - 1]),
      lastY: sy(last.value),
      lastV: last.value,
    };
  }, [pts, overlay]);

  if (!geom) return <p className="text-sm text-muted">Not enough observations to chart.</p>;

  const hoverPt = hoverIdx != null ? geom.points[hoverIdx] : null;
  const onMove = (e: ReactMouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * geom.W;
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < geom.points.length; i++) {
      const dist = Math.abs(geom.points[i].x - vbX);
      if (dist < bestD) {
        bestD = dist;
        best = i;
      }
    }
    setHoverIdx(best);
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${geom.W} ${geom.H}`}
        className="w-full"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
      <defs>
        <linearGradient id="macroArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.16" className="text-sky-500" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" className="text-sky-500" />
        </linearGradient>
      </defs>
      {geom.yTicks.map((t, i) => (
        <g key={i}>
          <line
            x1={48}
            x2={geom.W - geom.padR}
            y1={t.y}
            y2={t.y}
            className="text-border"
            stroke="currentColor"
            strokeWidth={0.5}
          />
          <text x={44} y={t.y + 3} textAnchor="end" className="fill-muted text-[10px]">
            {fmtNum(t.v, detail.unit)}
          </text>
        </g>
      ))}
      {geom.xTicks.map((t, i) => (
        <text key={i} x={t.x} y={geom.H - 8} textAnchor="middle" className="fill-muted text-[10px]">
          {t.label}
        </text>
      ))}
      {geom.zeroY != null && (
        <line
          x1={48}
          x2={geom.W - geom.padR}
          y1={geom.zeroY}
          y2={geom.zeroY}
          className="text-muted"
          stroke="currentColor"
          strokeWidth={0.8}
        />
      )}
      <path d={geom.area} fill="url(#macroArea)" />
      <path
        d={geom.line}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        className="text-sky-500"
      />
      {geom.overlayLine && (
        <path
          d={geom.overlayLine}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.6}
          strokeDasharray="4 3"
          className="text-amber-500"
        />
      )}
      <circle cx={geom.lastX} cy={geom.lastY} r={3} className="fill-sky-500" />
      <text
        x={geom.lastX - 6}
        y={geom.lastY - 7}
        textAnchor="end"
        className="fill-fg text-[11px] font-medium"
      >
        {fmtNum(geom.lastV, detail.unit)}
      </text>
      {hoverPt && (
        <g>
          <line
            x1={hoverPt.x}
            x2={hoverPt.x}
            y1={geom.padT}
            y2={geom.H - geom.padB}
            className="text-fg/40"
            stroke="currentColor"
            strokeWidth={0.8}
          />
          <circle cx={hoverPt.x} cy={hoverPt.y} r={3.5} className="fill-sky-500" />
        </g>
      )}
    </svg>
      {hoverPt && (
        <div
          className="pointer-events-none absolute z-10 whitespace-nowrap rounded-md border border-border bg-fg px-2 py-1 text-bg shadow-lg"
          style={{
            left: `${(hoverPt.x / geom.W) * 100}%`,
            top: `${(hoverPt.y / geom.H) * 100}%`,
            transform: `translate(${
              hoverPt.x / geom.W > 0.8 ? "-100%" : hoverPt.x / geom.W < 0.2 ? "0%" : "-50%"
            }, ${hoverPt.y / geom.H > 0.25 ? "calc(-100% - 10px)" : "10px"})`,
          }}
        >
          <div className="text-xs font-semibold tabular-nums">
            {fmtNum(hoverPt.v, detail.unit)}
          </div>
          <div className="text-[10px] opacity-70">{fmtDate(hoverPt.d)}</div>
        </div>
      )}
    </div>
  );
}

// --- cards (cockpit) ---------------------------------------------------------------------

function StatCard({ s, onClick }: { s: SeriesSummary; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col rounded-xl border border-border bg-surface p-3 text-left transition hover:border-fg/30"
    >
      <div className="truncate text-xs text-muted">{s.name}</div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <span className="text-2xl font-semibold tabular-nums text-fg">
          {fmtNum(s.latest, s.unit)}
        </span>
        <Sparkline values={s.spark} />
      </div>
      <div className="mt-1 flex items-center justify-between text-xs">
        <span className="text-muted">
          {s.geo} ·{" "}
          <span className={isStale(s.end_date, s.frequency) ? "text-amber-600 dark:text-amber-400" : ""}>
            {fmtMonthYear(s.end_date)}
          </span>
        </span>
        <span className={`tabular-nums ${deltaClass(s.chg_12m)}`}>
          {fmtDelta(s.chg_12m)} <span className="text-muted">12m</span>
        </span>
      </div>
    </button>
  );
}

// --- research table ----------------------------------------------------------------------

function ResearchTable({
  rows,
  sel,
  onPick,
}: {
  rows: SeriesSummary[];
  sel: string | null;
  onPick: (id: string) => void;
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-border text-xs text-muted">
          <th className="px-3 py-2 text-left font-medium">Indicator</th>
          <th className="px-2 py-2 text-right font-medium">Latest</th>
          <th className="hidden px-2 py-2 text-right font-medium sm:table-cell">1M</th>
          <th className="hidden px-2 py-2 text-right font-medium md:table-cell">3M</th>
          <th className="px-2 py-2 text-right font-medium">12M</th>
          <th className="hidden px-2 py-2 text-right font-medium lg:table-cell">YTD</th>
          <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Trend</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {rows.map((s) => (
          <tr
            key={s.series_id}
            onClick={() => onPick(s.series_id)}
            className={`cursor-pointer ${sel === s.series_id ? "bg-fg/10" : "hover:bg-fg/5"}`}
          >
            <td className="px-3 py-2">
              <div className="font-medium text-fg">{s.name}</div>
              <div className="text-xs text-muted">
                {s.geo} · {sourceLabel(s.source)} · {s.frequency} ·{" "}
                <span
                  className={
                    isStale(s.end_date, s.frequency)
                      ? "text-amber-600 dark:text-amber-400"
                      : ""
                  }
                  title={isStale(s.end_date, s.frequency) ? "stale vs expected cadence" : undefined}
                >
                  as of {fmtMonthYear(s.end_date)}
                </span>
              </div>
            </td>
            <td className="px-2 py-2 text-right tabular-nums text-fg">
              {fmtNum(s.latest, s.unit)}
            </td>
            <td className={`hidden px-2 py-2 text-right tabular-nums sm:table-cell ${deltaClass(s.chg_1m)}`}>
              {fmtDelta(s.chg_1m)}
            </td>
            <td className={`hidden px-2 py-2 text-right tabular-nums md:table-cell ${deltaClass(s.chg_3m)}`}>
              {fmtDelta(s.chg_3m)}
            </td>
            <td className={`px-2 py-2 text-right tabular-nums ${deltaClass(s.chg_12m)}`}>
              {fmtDelta(s.chg_12m)}
            </td>
            <td className={`hidden px-2 py-2 text-right tabular-nums lg:table-cell ${deltaClass(s.chg_ytd)}`}>
              {fmtDelta(s.chg_ytd)}
            </td>
            <td className="hidden px-3 py-2 text-right sm:table-cell">
              <div className="flex justify-end">
                <Sparkline values={s.spark} />
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --- page --------------------------------------------------------------------------------

/** The macro research browser. `category` (a sidebar submenu slug) filters to one bucket;
 *  undefined = the cross-theme cockpit + all sections. An unknown category yields an honest
 *  empty state. Modelled on a sell-side macro dashboard: headline cards, change table,
 *  featured chart. */
// Max series rows rendered for one category (population spans 200+ countries; the rest are
// reachable via search + the chart). Keeps the DOM light enough to stay responsive.
const MAX_LIST_ROWS = 60;

export function MacroBrowser({ category }: { category?: string }) {
  const [series, setSeries] = useState<SeriesSummary[]>([]);
  const [seriesState, setSeriesState] = useState<"loading" | "error" | "ready">("loading");
  const [clicked, setClicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<SeriesDetail | null>(null);
  const [errorFor, setErrorFor] = useState<string | null>(null);
  const [range, setRange] = useState<RangeKey>("5Y");
  const [overlay, setOverlay] = useState<SeriesDetail | null>(null);
  const [sortMode, setSortMode] = useState<"name" | "move">("name");
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetch("/api/macro/series", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: SeriesSummary[]) => {
        setSeries(d);
        setSeriesState("ready");
      })
      .catch(() => {
        setSeries([]);
        setSeriesState("error");
      });
  }, [category]);

  const visible = useMemo(() => {
    let v = category ? series.filter((s) => s.category === category) : series;
    const q = query.trim().toLowerCase();
    if (q) {
      v = v.filter((s) =>
        `${s.name} ${s.geo ?? ""} ${s.source} ${s.series_id}`.toLowerCase().includes(q)
      );
    }
    return v;
  }, [series, category, query]);

  // Selection is DERIVED: the clicked series while visible, else the first visible one.
  const sel =
    clicked && visible.some((s) => s.series_id === clicked)
      ? clicked
      : (visible[0]?.series_id ?? null);

  useEffect(() => {
    if (!sel) return;
    let stale = false;
    fetch(`/api/macro/series/${sel}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: SeriesDetail) => {
        if (stale) return;
        setDetail(d);
        setErrorFor(null);
      })
      .catch(() => {
        if (stale) return;
        setDetail(null);
        setErrorFor(sel);
      });
    return () => {
      stale = true;
    };
  }, [sel]);

  // companion overlay (e.g. IPCA realised vs Focus expectation) — fetched independently,
  // with an out-of-order guard, and only kept while it matches the current selection.
  useEffect(() => {
    const companion = sel ? OVERLAY[sel] : undefined;
    // No synchronous clear here (it would be a setState-in-effect); a series without a
    // companion is handled by the `shownOverlay` derivation below, which only keeps an
    // overlay that matches the current selection.
    if (!companion) return;
    let stale = false;
    fetch(`/api/macro/series/${companion}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: SeriesDetail) => {
        if (!stale) setOverlay(d);
      })
      .catch(() => {
        if (!stale) setOverlay(null);
      });
    return () => {
      stale = true;
    };
  }, [sel]);

  const shown = detail && detail.series_id === sel ? detail : null;
  const selSummary = visible.find((s) => s.series_id === sel) ?? null;
  // only overlay when it's the right companion for the current selection and same unit
  const shownOverlay =
    shown && overlay && OVERLAY[shown.series_id] === overlay.series_id &&
    overlay.unit === shown.unit
      ? overlay
      : null;

  // dashboard cockpit cards (landing only), grouped
  const cardGroups = useMemo(() => {
    if (category) return [];
    const byId = new Map(series.map((s) => [s.series_id, s]));
    return DASHBOARD_GROUPS.map((g) => ({
      title: g.title,
      cards: g.ids.map((id) => byId.get(id)).filter((s): s is SeriesSummary => !!s),
    })).filter((g) => g.cards.length > 0);
  }, [series, category]);

  // "what moved" strip (landing): biggest 12m % moves among price series (commodities /
  // markets / fx), where a percentage move is meaningful (unlike rate/ratio levels).
  const movers = useMemo(() => {
    if (category) return [];
    const priceCats = new Set(["commodities", "markets", "fx"]);
    return series
      .filter((s) => priceCats.has(s.category ?? "") && s.latest != null && s.chg_12m != null)
      .map((s) => {
        const prior = (s.latest as number) - (s.chg_12m as number);
        return { s, pct: prior ? ((s.chg_12m as number) / prior) * 100 : null };
      })
      .filter((m): m is { s: SeriesSummary; pct: number } => m.pct != null)
      .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
      .slice(0, 8);
  }, [series, category]);

  // sections: group visible series by category in sell-side order (landing only), each
  // section's rows ordered by the active sort (name = API order; move = |12m %| desc).
  const sections = useMemo(() => {
    const sortRows = (rows: SeriesSummary[]) => {
      if (sortMode !== "move") return rows;
      return [...rows].sort((a, b) => {
        const pa = pct12m(a);
        const pb = pct12m(b);
        if (pa == null) return 1;
        if (pb == null) return -1;
        return Math.abs(pb) - Math.abs(pa);
      });
    };
    // Cap a single category's rendered rows (a global indicator like population has 200+);
    // the chart/search still reach the rest. Landing sections are small (≤28) — left whole.
    if (category) return [{ key: category, rows: sortRows(visible).slice(0, MAX_LIST_ROWS) }];
    const by = new Map<string, SeriesSummary[]>();
    for (const s of visible) {
      const k = s.category ?? "other";
      (by.get(k) ?? by.set(k, []).get(k)!).push(s);
    }
    const ordered = [...by.keys()].sort(
      (a, b) => (CATEGORY_ORDER.indexOf(a) + 1 || 99) - (CATEGORY_ORDER.indexOf(b) + 1 || 99)
    );
    return ordered.map((k) => ({ key: k, rows: sortRows(by.get(k)!) }));
  }, [visible, category, sortMode]);

  // Arrow ↑/↓ move the selection through the visible list, in display order (terminal feel).
  const orderedIds = useMemo(
    () => sections.flatMap((s) => s.rows.map((r) => r.series_id)),
    [sections]
  );
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (orderedIds.length === 0) return;
      e.preventDefault();
      const cur = sel ? orderedIds.indexOf(sel) : -1;
      const next =
        e.key === "ArrowDown"
          ? Math.min(orderedIds.length - 1, cur + 1)
          : Math.max(0, cur - 1);
      setClicked(orderedIds[next]);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [orderedIds, sel]);

  // freshest observation across the store — the report date (research decks date everything)
  const asOf = useMemo(
    () => series.reduce((m, s) => (s.end_date && s.end_date > m ? s.end_date : m), ""),
    [series]
  );

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold tracking-tight text-fg">
          Macro{category ? <span className="text-muted"> · {CATEGORY_TITLE[category] ?? category}</span> : null}
        </h1>
        {asOf && (
          <span className="text-xs text-muted">
            {series.length} series · data as of {fmtDate(asOf)}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-muted">
        Central-bank &amp; macroeconomic series — BCB, IBGE, US Treasury, ECB, OECD, Eurostat,
        World Bank. QRP-managed reference data, independent of sym; never fabricated (no-data
        series omitted).
      </p>

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter series — name, country, source…"
        className="mt-4 w-full max-w-md rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-fg placeholder:text-muted focus:border-fg/30 focus:outline-none"
      />

      {seriesState === "error" && (
        <div className="mt-6 rounded-xl border border-border p-6 text-center text-sm text-muted">
          Couldn’t load series (API unreachable).
        </div>
      )}

      {/* cockpit cards (landing; hidden while searching to focus on results) */}
      {!category &&
        !query.trim() &&
        cardGroups.map((g) => (
          <div key={g.title} className="mt-5">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              {g.title}
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {g.cards.map((s) => (
                <StatCard key={s.series_id} s={s} onClick={() => setClicked(s.series_id)} />
              ))}
            </div>
          </div>
        ))}

      {/* category sub-cockpit: top highlights of the viewed bucket (respects the sort) */}
      {category && sections[0] && sections[0].rows.length > 0 && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {sections[0].rows.slice(0, 8).map((s) => (
            <StatCard key={s.series_id} s={s} onClick={() => setClicked(s.series_id)} />
          ))}
        </div>
      )}

      {/* 12-month movers (landing) */}
      {!category && !query.trim() && movers.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            12-month movers
          </h2>
          <div className="flex flex-wrap gap-2">
            {movers.map(({ s, pct }) => (
              <button
                key={s.series_id}
                type="button"
                onClick={() => setClicked(s.series_id)}
                className="flex items-center gap-2 rounded-full border border-border px-3 py-1 text-xs transition hover:bg-fg/5"
              >
                <span className="text-fg">{s.name}</span>
                <span className={`tabular-nums ${deltaClass(pct)}`}>
                  {pct > 0 ? "+" : ""}
                  {pct.toFixed(1)}%
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {category && COMPARISON_CATEGORIES.includes(category) && seriesState === "ready" && (
        <div className="mt-5">
          <MacroCompare key={category} category={category} series={visible} />
        </div>
      )}

      {/* featured chart */}
      {sel && (
        <div className="mt-5 rounded-xl border border-border bg-surface p-4">
          {shown && selSummary ? (
            <>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <div className="font-medium text-fg">
                    {shown.name} — {shown.geo}
                  </div>
                  <div className="text-xs text-muted">
                    {sourceLabel(shown.source)} · {shown.frequency} · {shown.unit} ·{" "}
                    {shown.observations.length.toLocaleString()} obs · as of{" "}
                    {fmtDate(selSummary.end_date)}
                  </div>
                </div>
                <div className="flex items-baseline gap-3">
                  <span className="text-2xl font-semibold tabular-nums text-fg">
                    {fmtNum(selSummary.latest, selSummary.unit)}
                  </span>
                  <span className={`text-sm tabular-nums ${deltaClass(selSummary.chg_12m)}`}>
                    {fmtDelta(selSummary.chg_12m)} <span className="text-muted">12m</span>
                  </span>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between">
                <div className="flex items-center gap-3 text-xs text-muted">
                  {shownOverlay && (
                    <>
                      <span className="flex items-center gap-1.5">
                        <span className="h-0.5 w-4 bg-sky-500" /> {shown.name}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-0.5 w-4 border-t-2 border-dashed border-amber-500" />
                        {shownOverlay.name}
                      </span>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  {(Object.keys(RANGES) as RangeKey[]).map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setRange(r)}
                      className={`rounded px-2 py-0.5 text-xs transition ${
                        range === r ? "bg-fg/10 text-fg" : "text-muted hover:bg-fg/5"
                      }`}
                    >
                      {r}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => downloadCsv(shown)}
                    className="ml-1 rounded border border-border px-2 py-0.5 text-xs text-muted transition hover:bg-fg/5"
                    title="Download full history as CSV"
                  >
                    CSV
                  </button>
                </div>
              </div>
              <div className="mt-1">
                <FeaturedChart
                  detail={sliceByRange(shown, range)}
                  overlay={shownOverlay ? sliceByRange(shownOverlay, range) : null}
                />
              </div>
            </>
          ) : errorFor === sel ? (
            <p className="text-sm text-muted">Couldn’t load series detail.</p>
          ) : (
            <p className="text-sm text-muted">Loading…</p>
          )}
        </div>
      )}

      {/* research tables, grouped by theme */}
      <div className="mt-6 space-y-6">
        {seriesState === "ready" && visible.length > 0 && (
          <div className="flex items-center justify-between gap-1 text-xs">
            <span className="text-muted/70">
              {category && visible.length > MAX_LIST_ROWS
                ? `showing ${MAX_LIST_ROWS} of ${visible.length} — search to narrow`
                : "↑↓ navigate · click a row to chart"}
            </span>
            <div className="flex items-center gap-1">
            <span className="mr-1 text-muted">Sort</span>
            {(["name", "move"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setSortMode(m)}
                className={`rounded px-2 py-0.5 transition ${
                  sortMode === m ? "bg-fg/10 text-fg" : "text-muted hover:bg-fg/5"
                }`}
              >
                {m === "name" ? "Name" : "12M move"}
              </button>
            ))}
            </div>
          </div>
        )}
        {seriesState === "ready" && visible.length === 0 && (
          <div className="rounded-xl border border-border p-6 text-center text-sm text-muted">
            {query.trim()
              ? `No series match “${query.trim()}”.`
              : category
                ? `No series in “${CATEGORY_TITLE[category] ?? category}”.`
                : "No macro series loaded."}
          </div>
        )}
        {sections.map(({ key, rows }) => (
          <section key={key}>
            {!category && (
              <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                {CATEGORY_TITLE[key] ?? key}
                <span className="ml-2 font-normal normal-case text-muted/70">{rows.length}</span>
              </h2>
            )}
            <div className="overflow-hidden rounded-xl border border-border">
              <ResearchTable rows={rows} sel={sel} onPick={setClicked} />
            </div>
          </section>
        ))}
      </div>

      {seriesState === "ready" && (
        <p className="mt-6 border-t border-border pt-3 text-xs leading-relaxed text-muted/80">
          Changes are absolute moves vs ~1 / 3 / 12 months before each series&rsquo; own latest
          observation; YTD is vs the prior calendar year-end. Sparklines show the last 48
          observations. Sources: BCB · IBGE · US&nbsp;Treasury · US&nbsp;BLS · ECB · OECD ·
          Eurostat · World&nbsp;Bank · market data (commodities, indices, FX) via yfinance.
          No-data series are omitted and values are never fabricated. Data reflects this
          environment&rsquo;s simulated-2026 feeds.
        </p>
      )}
    </div>
  );
}
