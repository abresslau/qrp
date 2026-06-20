"use client";

// Benchmark index level series — surfaces index_levels (e.g. MSCI World NR pulled via
// `sym msci-pull`). Lists the available index instruments and draws the selected one's level
// time-series. Theme-aware via currentColor (SSR-safe; no matchMedia needed). Always live.

import { useEffect, useMemo, useRef, useState } from "react";

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
type LevelSeries = {
  sym_id: number;
  name: string | null;
  currency: string | null;
  msci_code: string | null;
  variant: string | null;
  n_levels: number;
  since_start_return: number | null;
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
  return `${r >= 0 ? "+" : ""}${(r * 100).toFixed(1)}%`;
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
    return { x, y, line, area, ticks, min, max, n };
  }, [series]);

  if (!geom) return <p className="text-sm text-muted">Not enough points to chart.</p>;
  const first = series[0];
  const last = series[series.length - 1];
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
        <text x={PAD_L} y={H - 8} textAnchor="start" className="fill-muted" fontSize={11}>{first.date}</text>
        <text x={W - PAD_R} y={H - 8} textAnchor="end" className="fill-muted" fontSize={11}>{last.date}</text>
      </svg>
      <div className="mt-1 text-right text-xs text-muted">Level{currency ? ` (${currency})` : ""}</div>
    </div>
  );
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
  const [selected, setSelected] = useState<number | null>(null);
  const [data, setData] = useState<LevelSeries | null>(null);
  const [dataErr, setDataErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/sym/indexes", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`indexes -> ${r.status}`))))
      .then((rows: IndexSummary[]) => {
        if (!alive) return;
        setList(rows);
        if (rows.length > 0) setSelected(rows[0].sym_id);
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
            {list.map((ix) => {
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
                <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="Latest level" value={fmtLevel(data?.series.at(-1)?.level ?? sel.last_level)} />
                  <Stat label="As of" value={sel.last_date ?? "—"} />
                  <Stat label="Since start" value={fmtPct(data?.since_start_return)} />
                  <Stat label="From" value={sel.first_date ?? "—"} />
                </div>
                {dataErr ? (
                  <p className="text-sm text-rose-500">Could not load levels: {dataErr}</p>
                ) : loading || !data ? (
                  <p className="text-sm text-muted">Loading series…</p>
                ) : (
                  <LevelChart series={data.series} currency={sel.currency} />
                )}
              </>
            ) : null}
          </section>
        </div>
      )}

      <p className="mt-4 text-xs text-muted">
        Source: MSCI — free published end-of-day index levels (history from 1997; full
        since-inception requires a licensed MSCI feed). Levels are immutable and source-tagged.
      </p>
    </div>
  );
}
