"use client";

// Commodities — the daily commodity monitor (Bloomberg CMDTY/GLCO reference): a sector-grouped
// board (last / Δ / period returns / sparkline), a performance heatmap, and a click-through history
// chart. EOD, derive-on-read over commodities.price_daily (Tier-A continuous front-month). Theme-
// aware via currentColor; newest-wins fetch on the detail chart.

import { useEffect, useMemo, useRef, useState } from "react";

import { axisTickCount, dateAxisTicks, tickAnchor } from "@/lib/date-axis";

type BoardRow = {
  code: string;
  name: string;
  sector: string;
  sector_label: string;
  exchange: string;
  currency: string;
  unit: string;
  as_of_date: string | null;
  last: number | null;
  prev: number | null;
  chg_1d: number | null;
  pct_1d: number | null;
  pct_1w: number | null;
  pct_1m: number | null;
  pct_ytd: number | null;
  pct_1y: number | null;
  volume: number | null;
  spark: number[];
};
type HistPoint = { as_of_date: string; settle: number };
type History = {
  code: string;
  name: string;
  sector: string | null;
  unit: string | null;
  currency: string | null;
  exchange: string | null;
  points: HistPoint[];
};

// period columns shown in the board + selectable as the heatmap metric
const PERIODS = [
  { key: "pct_1d", label: "1D" },
  { key: "pct_1w", label: "1W" },
  { key: "pct_1m", label: "1M" },
  { key: "pct_ytd", label: "YTD" },
  { key: "pct_1y", label: "1Y" },
] as const;
type PeriodKey = (typeof PERIODS)[number]["key"];

// price formatting: more decimals for small-magnitude quotes (natgas ~3, corn ~600, gold ~2000)
const fmtPrice = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return "—";
  const d = Math.abs(v) >= 10 ? 2 : Math.abs(v) >= 1 ? 3 : 4;
  return v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
};
const fmtPct = (p: number | null | undefined): string =>
  p == null || !Number.isFinite(p) ? "—" : `${p >= 0 ? "+" : ""}${p.toFixed(2)}%`;
const fmtChg = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${fmtPrice(v)}`;
const toneClass = (p: number | null | undefined): string =>
  p == null || !Number.isFinite(p) || p === 0
    ? "text-muted"
    : p > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400";

// heatmap tile tint: green/red with opacity scaled by |pct|, saturating ~±6%
function heatStyle(p: number | null | undefined): React.CSSProperties {
  if (p == null || !Number.isFinite(p)) return { backgroundColor: "transparent" };
  const mag = Math.min(1, Math.abs(p) / 6);
  const a = 0.12 + mag * 0.5;
  return { backgroundColor: p >= 0 ? `rgba(16,185,129,${a})` : `rgba(244,63,94,${a})` };
}

// --- sparkline (no axes) -------------------------------------------------------------------------
function Sparkline({ data }: { data: number[] }) {
  const d = useMemo(() => {
    if (!data || data.length < 2) return null;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const span = max - min || 1;
    const n = data.length;
    return data
      .map((v, i) => `${i === 0 ? "M" : "L"}${((i / (n - 1)) * 100).toFixed(1)},${(22 - ((v - min) / span) * 20 - 1).toFixed(1)}`)
      .join(" ");
  }, [data]);
  if (!d) return null;
  const up = data[data.length - 1] >= data[0];
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="h-6 w-full" aria-hidden>
      <path
        d={d}
        fill="none"
        strokeWidth={1.2}
        vectorEffect="non-scaling-stroke"
        className={up ? "stroke-emerald-500" : "stroke-rose-500"}
      />
    </svg>
  );
}

// --- history line chart (date axis via lib/date-axis) --------------------------------------------
const W = 900;
const H = 300;
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 30;

function HistoryChart({ hist }: { hist: History }) {
  const geom = useMemo(() => {
    const s = hist.points;
    if (s.length < 2) return null;
    const vs = s.map((p) => p.settle);
    const min = Math.min(...vs);
    const max = Math.max(...vs);
    const span = max - min || 1;
    const n = s.length;
    const x = (i: number) => PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R);
    const y = (v: number) => PAD_T + (1 - (v - min) / span) * (H - PAD_T - PAD_B);
    const line = s.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.settle).toFixed(1)}`).join(" ");
    const up = s[n - 1].settle >= s[0].settle;
    const yticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ v: min + f * span, yy: y(min + f * span) }));
    const times = s.map((p) => new Date(p.as_of_date).getTime());
    const xticks = dateAxisTicks(times[0], times[n - 1], axisTickCount(W - PAD_L - PAD_R)).map((tk) => {
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
    return { line, yticks, xticks, up };
  }, [hist]);
  if (!geom) return <p className="text-sm text-muted">Not enough history to chart.</p>;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full text-fg" role="img" aria-label="Price history">
      {geom.yticks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} x2={W - PAD_R} y1={t.yy} y2={t.yy} stroke="currentColor" strokeOpacity={0.12} />
          <text x={PAD_L - 8} y={t.yy + 3} textAnchor="end" className="fill-muted" fontSize={11}>
            {fmtPrice(t.v)}
          </text>
        </g>
      ))}
      <path
        d={geom.line}
        fill="none"
        strokeWidth={1.6}
        strokeLinejoin="round"
        className={geom.up ? "stroke-emerald-500" : "stroke-rose-500"}
      />
      {geom.xticks.map((t, i) => (
        <text key={i} x={t.x} y={H - 9} textAnchor={tickAnchor(i)} className="fill-muted" fontSize={11}>
          {t.label}
        </text>
      ))}
    </svg>
  );
}

function Seg<T extends string>({ value, options, onChange }: { value: T; options: readonly { key: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={`px-2.5 py-1 ${value === o.key ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function CommoditiesPage() {
  const [board, setBoard] = useState<BoardRow[] | null>(null);
  const [boardErr, setBoardErr] = useState<string | null>(null);
  const [view, setView] = useState<"table" | "heatmap">("table");
  const [heatMetric, setHeatMetric] = useState<PeriodKey>("pct_1d");

  const [selCode, setSelCode] = useState<string | null>(null);
  const [hist, setHist] = useState<History | null>(null);
  const [histWindow, setHistWindow] = useState<"1Y" | "5Y" | "MAX">("5Y");
  const histAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/commodities/board", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`board -> ${r.status}`))))
      .then((rows: BoardRow[]) => alive && setBoard(rows))
      .catch((e) => alive && setBoardErr(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (selCode == null) return;
    histAbort.current?.abort();
    const ac = new AbortController();
    histAbort.current = ac;
    void (async () => {
      try {
        const r = await fetch(`/api/commodities/history/${selCode}?window=${histWindow}`, {
          cache: "no-store",
          signal: ac.signal,
        });
        if (!r.ok) throw new Error(`${r.status}`);
        const d: History = await r.json();
        if (!ac.signal.aborted) setHist(d);
      } catch {
        /* keep prior */
      }
    })();
    return () => ac.abort();
  }, [selCode, histWindow]);

  // group board rows by sector, preserving the server's sector/name ordering
  const groups = useMemo(() => {
    if (!board) return [];
    const out: { sector: string; label: string; rows: BoardRow[] }[] = [];
    for (const r of board) {
      let g = out.find((x) => x.sector === r.sector);
      if (!g) {
        g = { sector: r.sector, label: r.sector_label, rows: [] };
        out.push(g);
      }
      g.rows.push(r);
    }
    return out;
  }, [board]);

  const asOf =
    board?.reduce<string | null>(
      (m, r) => (r.as_of_date && (m === null || r.as_of_date > m) ? r.as_of_date : m),
      null,
    ) ?? null;
  const sel = board?.find((r) => r.code === selCode) ?? null;

  return (
    <div className="w-full">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg">Commodities — daily monitor</h1>
          <p className="mt-1 text-sm text-muted">
            Continuous front-month futures across energy, metals, agriculture, softs and livestock
            (EOD). Period returns and the sparkline are derived on read from the stored series.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Seg
            value={view}
            options={[
              { key: "table", label: "Board" },
              { key: "heatmap", label: "Heatmap" },
            ] as const}
            onChange={setView}
          />
          {view === "heatmap" ? (
            <Seg value={heatMetric} options={PERIODS} onChange={setHeatMetric} />
          ) : null}
        </div>
      </header>

      {boardErr ? (
        <p className="text-sm text-rose-500">Could not load the board: {boardErr}</p>
      ) : board == null ? (
        <p className="text-sm text-muted">Loading commodities…</p>
      ) : board.length === 0 ? (
        <p className="text-sm text-muted">No commodity prices loaded yet — run `commodities price load`.</p>
      ) : view === "table" ? (
        <BoardTable groups={groups} selCode={selCode} onSelect={setSelCode} />
      ) : (
        <Heatmap groups={groups} metric={heatMetric} selCode={selCode} onSelect={setSelCode} />
      )}

      {/* detail: history chart for the selected commodity */}
      {sel ? (
        <section className="mt-5 rounded-xl border border-border bg-surface p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-fg">
                {sel.name} <span className="text-muted">· {sel.code}</span>
              </div>
              <div className="mt-0.5 text-xs text-muted">
                {sel.exchange} · {sel.unit} · {sel.currency}
                {sel.as_of_date ? ` · as of ${sel.as_of_date}` : ""}
                {sel.last != null ? ` · last ${fmtPrice(sel.last)}` : ""}
                <span className={`ml-1 ${toneClass(sel.pct_1d)}`}>
                  {sel.pct_1d != null ? `(${fmtPct(sel.pct_1d)} 1D)` : ""}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
                {(["1Y", "5Y", "MAX"] as const).map((w) => (
                  <button
                    key={w}
                    type="button"
                    onClick={() => setHistWindow(w)}
                    className={`px-2 py-0.5 ${histWindow === w ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
                  >
                    {w}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setSelCode(null)}
                title="close"
                className="rounded-md border border-border px-2 py-0.5 text-xs text-muted transition hover:text-fg"
              >
                ✕
              </button>
            </div>
          </div>
          {hist && hist.code === sel.code ? (
            <HistoryChart hist={hist} />
          ) : (
            <p className="text-sm text-muted">Loading history…</p>
          )}
        </section>
      ) : null}

      <p className="mt-4 text-xs text-muted">
        Source: Yahoo Finance continuous front-month (`=F`), raw / non-back-adjusted, EOD. v1 is
        Tier-A (one continuous series per commodity); the dated-futures curve, open interest and our
        own roll/back-adjustment are a later phase.
        {asOf ? ` Latest as-of ${asOf}.` : ""}
      </p>
    </div>
  );
}

// --- board table (sector-grouped) ----------------------------------------------------------------
function BoardTable({
  groups,
  selCode,
  onSelect,
}: {
  groups: { sector: string; label: string; rows: BoardRow[] }[];
  selCode: string | null;
  onSelect: (code: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border text-xs text-muted">
            <th className="px-3 py-2 text-left font-medium">Commodity</th>
            <th className="px-3 py-2 text-right font-medium">Last</th>
            <th className="px-3 py-2 text-right font-medium">Chg</th>
            {PERIODS.map((p) => (
              <th key={p.key} className="px-3 py-2 text-right font-medium">
                {p.label}
              </th>
            ))}
            <th className="px-3 py-2 text-right font-medium">90d</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <SectorBlock key={g.sector} group={g} selCode={selCode} onSelect={onSelect} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectorBlock({
  group,
  selCode,
  onSelect,
}: {
  group: { sector: string; label: string; rows: BoardRow[] };
  selCode: string | null;
  onSelect: (code: string) => void;
}) {
  return (
    <>
      <tr className="bg-fg/[0.03]">
        <td colSpan={9} className="px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
          {group.label}
        </td>
      </tr>
      {group.rows.map((r) => {
        const active = r.code === selCode;
        return (
          <tr
            key={r.code}
            onClick={() => onSelect(r.code)}
            className={`cursor-pointer border-b border-border/60 transition ${active ? "bg-fg/10" : "hover:bg-fg/5"}`}
          >
            <td className="px-3 py-1.5">
              <span className="font-medium text-fg">{r.name}</span>
              <span className="ml-1.5 text-xs text-muted">{r.unit}</span>
            </td>
            <td className="px-3 py-1.5 text-right tabular-nums text-fg">{fmtPrice(r.last)}</td>
            <td className={`px-3 py-1.5 text-right tabular-nums ${toneClass(r.pct_1d)}`}>{fmtChg(r.chg_1d)}</td>
            {PERIODS.map((p) => (
              <td key={p.key} className={`px-3 py-1.5 text-right tabular-nums ${toneClass(r[p.key])}`}>
                {fmtPct(r[p.key])}
              </td>
            ))}
            <td className="px-3 py-1.5">
              <div className="ml-auto h-6 w-24">
                <Sparkline data={r.spark} />
              </div>
            </td>
          </tr>
        );
      })}
    </>
  );
}

// --- heatmap (sector-grouped performance tiles) --------------------------------------------------
function Heatmap({
  groups,
  metric,
  selCode,
  onSelect,
}: {
  groups: { sector: string; label: string; rows: BoardRow[] }[];
  metric: PeriodKey;
  selCode: string | null;
  onSelect: (code: string) => void;
}) {
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <div key={g.sector}>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{g.label}</div>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-4 2xl:grid-cols-6">
            {g.rows.map((r) => {
              const p = r[metric];
              const active = r.code === selCode;
              return (
                <button
                  key={r.code}
                  type="button"
                  onClick={() => onSelect(r.code)}
                  style={heatStyle(p)}
                  className={`flex flex-col gap-0.5 rounded-lg border p-2.5 text-left transition ${
                    active ? "border-fg/50" : "border-border hover:border-fg/30"
                  }`}
                >
                  <span className="truncate text-xs font-medium text-fg">{r.name}</span>
                  <span className="text-lg font-semibold tabular-nums text-fg">{fmtPct(p)}</span>
                  <span className="text-[11px] tabular-nums text-muted">{fmtPrice(r.last)} {r.unit}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
