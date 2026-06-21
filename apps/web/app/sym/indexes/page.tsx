"use client";

// Benchmark index level series — surfaces index_levels (e.g. MSCI World NR pulled via
// `sym msci-pull`). Lists the available index instruments and draws the selected one's level
// time-series. Theme-aware via currentColor (SSR-safe; no matchMedia needed). Always live.

import { useEffect, useMemo, useRef, useState } from "react";

import { dateAxisTicks, tickAnchor } from "@/lib/date-axis";

type IndexSummary = {
  sym_id: number;
  name: string | null;
  currency: string | null;
  msci_code: string | null;
  variant: string | null; // NETR / STRD / GRTR
  n_levels: number;
  first_date: string | null;
  last_date: string | null;
  last_level: number | null;
};
type LevelPoint = { date: string; level: number };
type Trailing = {
  mtd: number | null;
  qtd: number | null;
  ytd: number | null;
  "1y": number | null;
  "2y": number | null;
  "3y": number | null;
  "5y": number | null;
  "10y": number | null;
};
type LevelSeries = {
  sym_id: number;
  name: string | null;
  currency: string | null;
  msci_code: string | null;
  variant: string | null;
  n_levels: number;
  since_start_return: number | null;
  trailing: Trailing;
  series: LevelPoint[];
};

const VARIANT_LABEL: Record<string, string> = {
  NETR: "Net Return",
  STRD: "Price Return",
  GRTR: "Gross Return",
};
const variantLabel = (v: string | null) => (v ? (VARIANT_LABEL[v] ?? v) : "—");

function fmtLevel(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(r: number | null | undefined): string {
  if (r == null || !Number.isFinite(r)) return "—";
  return `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}

// --- SVG level line chart (viewBox-scaled; theme via currentColor) -------------------------------
const W = 900;
const H = 280;
const PAD_L = 64;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 28;

function LevelChart({ series, currency }: { series: LevelPoint[]; currency: string | null }) {
  const geom = useMemo(() => {
    if (series.length < 2) return null;
    const levels = series.map((p) => p.level);
    const min = Math.min(...levels);
    const max = Math.max(...levels);
    const span = max - min || 1;
    const n = series.length;
    const x = (i: number) => PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R);
    const y = (lv: number) => PAD_T + (1 - (lv - min) / span) * (H - PAD_T - PAD_B);
    const line = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.level).toFixed(1)}`).join(" ");
    const area = `${line} L${x(n - 1).toFixed(1)},${(H - PAD_B).toFixed(1)} L${x(0).toFixed(1)},${(H - PAD_B).toFixed(1)} Z`;
    // 4 horizontal gridlines / y labels
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ v: min + f * span, yy: y(min + f * span) }));
    // "Nice" date ticks (matplotlib-style) at round boundaries across the series' date range.
    // The chart is index-scaled (not time-scaled), so map each tick time to its nearest observation.
    const times = series.map((p) => new Date(p.date).getTime());
    const xticks = dateAxisTicks(times[0], times[n - 1], 6).map((tk) => {
      let idx = 0;
      let best = Infinity;
      for (let i = 0; i < times.length; i++) {
        const dd = Math.abs(times[i] - tk.t);
        if (dd < best) {
          best = dd;
          idx = i;
        }
      }
      return { x: x(idx), label: tk.label };
    });
    return { x, y, line, area, ticks, xticks, min, max, n };
  }, [series]);

  if (!geom) return <p className="text-sm text-muted">Not enough points to chart.</p>;
  return (
    <div className="text-fg">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img" aria-label="Index level time series">
        {geom.ticks.map((t, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={W - PAD_R} y1={t.yy} y2={t.yy} stroke="currentColor" strokeOpacity={0.12} strokeWidth={1} />
            <text x={PAD_L - 8} y={t.yy + 3} textAnchor="end" className="fill-muted" fontSize={11}>
              {fmtLevel(t.v)}
            </text>
          </g>
        ))}
        <path d={geom.area} fill="currentColor" fillOpacity={0.08} stroke="none" />
        <path d={geom.line} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round" />
        {geom.xticks.map((t, i) => (
          <text key={i} x={t.x} y={H - 8} textAnchor={tickAnchor(i, geom.xticks.length)} className="fill-muted" fontSize={11}>
            {t.label}
          </text>
        ))}
      </svg>
      <div className="mt-1 text-right text-xs text-muted">Level{currency ? ` (${currency})` : ""}</div>
    </div>
  );
}

// --- monthly calendar returns (Year | Jan … Dec | YTD) from the level series ---------------------
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
type MonthRow = { year: number; months: (number | null)[]; ytd: number | null };

// Month-over-month returns from month-end levels: ret(y,m) = monthEnd(y,m) / monthEnd(prev month) − 1.
// YTD = last month-end of the year / prior year-end (or the year's first observation in the inception
// year). Years with no computable month are dropped (e.g. a 2-day inception stub). Newest year first.
function monthlyReturnRows(series: LevelPoint[]): MonthRow[] {
  if (series.length < 2) return [];
  const monthEnd = new Map<string, number>(); // "YYYY-MM" -> last level in that month
  const firstOfYear = new Map<number, number>();
  for (const p of series) {
    monthEnd.set(p.date.slice(0, 7), p.level); // series is date-ascending → last write wins
    const y = Number(p.date.slice(0, 4));
    if (!firstOfYear.has(y)) firstOfYear.set(y, p.level);
  }
  const me = (y: number, m: number) => monthEnd.get(`${y}-${String(m + 1).padStart(2, "0")}`);
  const years = [...new Set([...monthEnd.keys()].map((k) => Number(k.slice(0, 4))))].sort((a, b) => a - b);
  const rows = years.map((y): MonthRow => {
    const months = Array.from({ length: 12 }, (_, m) => {
      const cur = me(y, m);
      if (cur == null) return null;
      const prev = m === 0 ? me(y - 1, 11) : me(y, m - 1);
      return prev != null && prev > 0 ? cur / prev - 1 : null;
    });
    let lastM = -1;
    for (let m = 11; m >= 0; m--) if (me(y, m) != null) { lastM = m; break; }
    const cur = lastM >= 0 ? me(y, lastM)! : null;
    const base = me(y - 1, 11) ?? firstOfYear.get(y);
    const ytd = cur != null && base != null && base > 0 ? cur / base - 1 : null;
    return { year: y, months, ytd };
  });
  return rows.filter((r) => r.months.some((m) => m != null)).reverse();
}

function MonthlyTable({ series }: { series: LevelPoint[] }) {
  const rows = useMemo(() => monthlyReturnRows(series), [series]);
  if (rows.length === 0) return null;
  const cell = (r: number | null) => {
    if (r == null) return <span className="text-muted/40">·</span>;
    const cls = r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
    return <span className={cls}>{`${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}`}</span>;
  };
  return (
    <div className="mt-5">
      <div className="mb-1 text-xs uppercase tracking-wide text-muted">Monthly returns (%)</div>
      <div className="overflow-x-auto">
        <table className="w-full text-right text-xs tabular-nums [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
          <thead className="text-muted">
            <tr className="border-b border-border">
              <th className="px-2 py-1 text-left font-medium">Year</th>
              {MONTHS.map((m) => (
                <th key={m} className="px-2 py-1 font-medium">{m}</th>
              ))}
              <th className="px-2 py-1 font-semibold text-fg">YTD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.year} className="border-b border-border/40 hover:bg-fg/5">
                <td className="px-2 py-1 text-left font-medium text-fg">{r.year}</td>
                {r.months.map((m, i) => (
                  <td key={i} className="px-2 py-1">{cell(m)}</td>
                ))}
                <td className="px-2 py-1 font-semibold">{cell(r.ytd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Ret({ v }: { v: number | null | undefined }) {
  if (v == null || !Number.isFinite(v)) return <span className="text-muted">—</span>;
  const cls = v >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
  return <span className={cls}>{fmtPct(v)}</span>;
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-3">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-fg">{value}</div>
    </div>
  );
}

export default function IndexesPage() {
  const [list, setList] = useState<IndexSummary[] | null>(null);
  const [listErr, setListErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [data, setData] = useState<LevelSeries | null>(null);
  const [dataErr, setDataErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState<"YTD" | "1Y" | "2Y" | "3Y" | "5Y" | "10Y" | "Max">("Max");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/sym/indexes", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`indexes -> ${r.status}`))))
      .then((rows: IndexSummary[]) => {
        if (!alive) return;
        // MSCI indexes first (the benchmark set this page is built for), then alphabetical.
        const sorted = [...rows].sort((a, b) => {
          const am = a.msci_code ? 0 : 1;
          const bm = b.msci_code ? 0 : 1;
          return am !== bm ? am - bm : (a.name ?? "").localeCompare(b.name ?? "");
        });
        setList(sorted);
        // default to the marquee MSCI World Net, else the first index
        const marquee = sorted.find((r) => /MSCI World Net/i.test(r.name ?? "")) ?? sorted[0];
        if (marquee) setSelected(marquee.sym_id);
      })
      .catch((e) => alive && setListErr(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (selected == null) return;
    abortRef.current?.abort(); // newest-wins when switching indexes
    const ac = new AbortController();
    abortRef.current = ac;
    void (async () => {
      setLoading(true);
      setDataErr(null);
      setData(null); // drop the previous index's series so its stats don't show under the new header
      try {
        const r = await fetch(`/api/sym/indexes/${selected}/levels`, {
          cache: "no-store",
          signal: ac.signal,
        });
        if (!r.ok) throw new Error(`levels -> ${r.status}`);
        const d: LevelSeries = await r.json();
        if (ac.signal.aborted) return;
        setData(d);
        setLoading(false);
      } catch (e) {
        if (ac.signal.aborted) return;
        setDataErr(String(e));
        setLoading(false);
      }
    })();
    return () => ac.abort();
  }, [selected]);

  const sel = useMemo(() => list?.find((i) => i.sym_id === selected) ?? null, [list, selected]);

  // chart slice for the selected range (stats stay full-history; only the chart zooms)
  const chartSeries = useMemo(() => {
    const s = data?.series ?? [];
    if (range === "Max" || s.length < 2) return s;
    const last = s[s.length - 1];
    let cutoff: string;
    if (range === "YTD") {
      cutoff = `${last.date.slice(0, 4)}-01-01`;
    } else {
      const yrs = { "1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10 }[range];
      cutoff = new Date(new Date(last.date).getTime() - yrs * 365 * 864e5).toISOString().slice(0, 10);
    }
    const sliced = s.filter((p) => p.date >= cutoff);
    return sliced.length >= 2 ? sliced : s;
  }, [data, range]);

  return (
    <div className="w-full">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-fg">Benchmark indexes</h1>
        <p className="mt-1 text-sm text-muted">
          Level time-series for benchmark indexes in the warehouse. MSCI series are pulled directly
          from MSCI&apos;s free published EOD data (Net / Price / Gross are separate instruments).
        </p>
      </header>

      {listErr ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-rose-500">
          Could not load indexes: {listErr}
        </p>
      ) : list == null ? (
        <p className="text-sm text-muted">Loading indexes…</p>
      ) : list.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
          No index level data yet. Pull one with{" "}
          <code className="rounded bg-fg/10 px-1">sym msci-pull --msci-code 990100 --variant NR --name &quot;MSCI World Net (USD)&quot;</code>.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          {/* index list */}
          <nav className="flex flex-col gap-1" aria-label="indexes">
            {list.length > 8 ? (
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter indexes…"
                aria-label="filter indexes"
                className="mb-1 rounded-lg border border-border bg-bg px-2.5 py-1.5 text-sm text-fg placeholder:text-muted"
              />
            ) : null}
            {list
              .filter((ix) => (ix.name ?? "").toLowerCase().includes(filter.toLowerCase()))
              .map((ix) => {
              const active = ix.sym_id === selected;
              return (
                <button
                  key={ix.sym_id}
                  type="button"
                  onClick={() => setSelected(ix.sym_id)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                    active ? "border-fg/40 bg-fg/10 text-fg" : "border-border text-muted hover:text-fg"
                  }`}
                >
                  <div className="font-medium text-fg">{ix.name ?? `#${ix.sym_id}`}</div>
                  <div className="text-xs text-muted">
                    {variantLabel(ix.variant)} · {ix.currency ?? "—"} · {ix.n_levels.toLocaleString()} obs
                  </div>
                </button>
              );
            })}
          </nav>

          {/* selected index detail */}
          <section className="rounded-xl border border-border bg-surface p-4">
            {sel ? (
              <>
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <div className="text-lg font-semibold text-fg">{sel.name ?? `#${sel.sym_id}`}</div>
                    <div className="text-xs text-muted">
                      {variantLabel(sel.variant)}
                      {sel.msci_code ? ` · MSCI ${sel.msci_code}` : ""} · {sel.currency ?? "—"}
                    </div>
                  </div>
                </div>
                <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="Latest level" value={fmtLevel(data?.series.at(-1)?.level ?? sel.last_level)} />
                  <Stat label="As of" value={sel.last_date ?? "—"} />
                  <Stat label="Since start" value={fmtPct(data?.since_start_return)} />
                  <Stat label="From" value={sel.first_date ?? "—"} />
                </div>
                {/* trailing returns (computed from the level series) */}
                <div className="mb-4 grid grid-cols-4 gap-2 lg:grid-cols-8">
                  <Stat label="MTD" value={<Ret v={data?.trailing?.mtd} />} />
                  <Stat label="QTD" value={<Ret v={data?.trailing?.qtd} />} />
                  <Stat label="YTD" value={<Ret v={data?.trailing?.ytd} />} />
                  <Stat label="1Y" value={<Ret v={data?.trailing?.["1y"]} />} />
                  <Stat label="2Y" value={<Ret v={data?.trailing?.["2y"]} />} />
                  <Stat label="3Y" value={<Ret v={data?.trailing?.["3y"]} />} />
                  <Stat label="5Y" value={<Ret v={data?.trailing?.["5y"]} />} />
                  <Stat label="10Y" value={<Ret v={data?.trailing?.["10y"]} />} />
                </div>
                {dataErr ? (
                  <p className="text-sm text-rose-500">Could not load levels: {dataErr}</p>
                ) : loading || !data ? (
                  <p className="text-sm text-muted">Loading series…</p>
                ) : (
                  <>
                    <div className="mb-1 flex justify-end">
                      <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
                        {(["YTD", "1Y", "2Y", "3Y", "5Y", "10Y", "Max"] as const).map((rg) => (
                          <button
                            key={rg}
                            type="button"
                            onClick={() => setRange(rg)}
                            className={`px-2 py-0.5 ${
                              range === rg ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
                            }`}
                          >
                            {rg}
                          </button>
                        ))}
                      </div>
                    </div>
                    <LevelChart series={chartSeries} currency={sel.currency} />
                    <MonthlyTable series={data.series} />
                  </>
                )}
              </>
            ) : null}
          </section>
        </div>
      )}

      <p className="mt-4 text-xs text-muted">
        Source: MSCI — free published end-of-day index levels (from 1997 where available — see each
        index&apos;s &ldquo;From&rdquo;; full since-inception requires a licensed MSCI feed). Levels are
        immutable and source-tagged.
      </p>
    </div>
  );
}
