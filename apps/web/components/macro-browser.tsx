"use client";

import { useEffect, useMemo, useState } from "react";

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

// Headline indicators for the dashboard cockpit (landing only), in display order.
const DASHBOARD: { id: string; label: string }[] = [
  { id: "BCB:SELIC_TARGET", label: "Selic (target)" },
  { id: "BCB:IPCA_12M", label: "IPCA (12m)" },
  { id: "BCB:FOCUS_IPCA_12M", label: "IPCA expect. (12m)" },
  { id: "BCB:BRLUSD", label: "BRL / USD" },
  { id: "IBGE:UNEMP", label: "Unemployment" },
  { id: "BCB:IBCBR_SA", label: "IBC-Br activity" },
  { id: "BCB:DBGG", label: "Gross debt (% GDP)" },
  { id: "BCB:CURRENT_ACCOUNT", label: "Current account" },
  { id: "UST:PAR_YIELD:10Y", label: "UST 10y" },
  { id: "UST:PAR_YIELD:2Y", label: "UST 2y" },
];

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

function FeaturedChart({ detail }: { detail: SeriesDetail }) {
  const pts = detail.observations;
  const geom = useMemo(() => {
    if (pts.length < 2) return null;
    const W = 760;
    const H = 300;
    const padL = 48;
    const padR = 16;
    const padT = 16;
    const padB = 26;
    const xs = pts.map((p) => new Date(p.obs_date).getTime());
    const ys = pts.map((p) => p.value);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const sx = (t: number) => padL + ((t - minX) / spanX) * (W - padL - padR);
    const sy = (v: number) => H - padB - ((v - minY) / spanY) * (H - padT - padB);
    const line = pts
      .map((p, i) => `${i ? "L" : "M"}${sx(xs[i]).toFixed(1)},${sy(p.value).toFixed(1)}`)
      .join(" ");
    const area = `${line} L${sx(maxX).toFixed(1)},${(H - padB).toFixed(1)} L${sx(minX).toFixed(1)},${(H - padB).toFixed(1)} Z`;
    // 4 horizontal gridlines with value labels
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const v = minY + f * spanY;
      return { y: sy(v), v };
    });
    // ~5 dated x ticks
    const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const t = minX + f * spanX;
      return { x: sx(t), label: new Date(t).getFullYear().toString() };
    });
    const last = pts[pts.length - 1];
    return {
      W, H, padR, line, area, yTicks, xTicks,
      lastX: sx(xs[xs.length - 1]),
      lastY: sy(last.value),
      lastV: last.value,
    };
  }, [pts]);

  if (!geom) return <p className="text-sm text-muted">Not enough observations to chart.</p>;
  return (
    <svg viewBox={`0 0 ${geom.W} ${geom.H}`} className="w-full">
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
      <path d={geom.area} fill="url(#macroArea)" />
      <path
        d={geom.line}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        className="text-sky-500"
      />
      <circle cx={geom.lastX} cy={geom.lastY} r={3} className="fill-sky-500" />
      <text
        x={geom.lastX - 6}
        y={geom.lastY - 7}
        textAnchor="end"
        className="fill-fg text-[11px] font-medium"
      >
        {fmtNum(geom.lastV, detail.unit)}
      </text>
    </svg>
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
        <span className="text-muted">{s.geo}</span>
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
                {s.geo} · {sourceLabel(s.source)} · {s.frequency}
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
export function MacroBrowser({ category }: { category?: string }) {
  const [series, setSeries] = useState<SeriesSummary[]>([]);
  const [seriesState, setSeriesState] = useState<"loading" | "error" | "ready">("loading");
  const [clicked, setClicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<SeriesDetail | null>(null);
  const [errorFor, setErrorFor] = useState<string | null>(null);

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

  const visible = useMemo(
    () => (category ? series.filter((s) => s.category === category) : series),
    [series, category]
  );

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

  const shown = detail && detail.series_id === sel ? detail : null;
  const selSummary = visible.find((s) => s.series_id === sel) ?? null;

  // dashboard cockpit cards (landing only)
  const cards = useMemo(() => {
    if (category) return [];
    const byId = new Map(series.map((s) => [s.series_id, s]));
    return DASHBOARD.map((d) => byId.get(d.id)).filter((s): s is SeriesSummary => !!s);
  }, [series, category]);

  // sections: group visible series by category in sell-side order (landing only)
  const sections = useMemo(() => {
    if (category) return [{ key: category, rows: visible }];
    const by = new Map<string, SeriesSummary[]>();
    for (const s of visible) {
      const k = s.category ?? "other";
      (by.get(k) ?? by.set(k, []).get(k)!).push(s);
    }
    const ordered = [...by.keys()].sort(
      (a, b) => (CATEGORY_ORDER.indexOf(a) + 1 || 99) - (CATEGORY_ORDER.indexOf(b) + 1 || 99)
    );
    return ordered.map((k) => ({ key: k, rows: by.get(k)! }));
  }, [visible, category]);

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">
        Macro{category ? <span className="text-muted"> · {CATEGORY_TITLE[category] ?? category}</span> : null}
      </h1>
      <p className="mt-1 text-sm text-muted">
        Central-bank &amp; macroeconomic series — BCB, IBGE, US Treasury, ECB, OECD, Eurostat,
        World Bank. QRP-managed reference data, independent of sym; never fabricated (no-data
        series omitted).
      </p>

      {seriesState === "error" && (
        <div className="mt-6 rounded-xl border border-border p-6 text-center text-sm text-muted">
          Couldn’t load series (API unreachable).
        </div>
      )}

      {/* cockpit cards (landing) */}
      {!category && cards.length > 0 && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {cards.map((s) => (
            <StatCard key={s.series_id} s={s} onClick={() => setClicked(s.series_id)} />
          ))}
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
              <div className="mt-3">
                <FeaturedChart detail={shown} />
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
        {seriesState === "ready" && visible.length === 0 && (
          <div className="rounded-xl border border-border p-6 text-center text-sm text-muted">
            {category ? `No series in “${CATEGORY_TITLE[category] ?? category}”.` : "No macro series loaded."}
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
    </div>
  );
}
