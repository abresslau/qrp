"use client";

import { useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type Benchmark = Schemas["Benchmark"];
type Analytics = Schemas["Analytics"];

const WINDOWS = ["ALL", "1Y", "YTD", "6M", "3M"] as const;

function pct(r: number | null | undefined): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function num(r: number | null | undefined, dp = 2): string {
  return r == null ? "—" : r.toFixed(dp);
}
function tone(r: number | null | undefined): string {
  if (r == null) return "text-fg";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

function Metric({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded-lg border border-border bg-bg px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${cls ?? "text-fg"}`}>{value}</div>
    </div>
  );
}

export function AnalyticsPanel({ pid }: { pid: string }) {
  const [benches, setBenches] = useState<Benchmark[]>([]);
  const [bench, setBench] = useState<number | null>(null);
  const [win, setWin] = useState<string>("ALL");
  const [a, setA] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/analytics/benchmarks", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Benchmark[]) => {
        setBenches(d);
        const sp = d.find((x) => x.name === "S&P 500") ?? d[0];
        if (sp) setBench(sp.id);
      })
      .catch(() => setBenches([]));
  }, []);

  useEffect(() => {
    if (bench == null) return;
    setLoading(true);
    fetch(`/api/portfolios/${pid}/analytics?benchmark=${bench}&window=${win}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Analytics) => setA(d))
      .catch(() => setA(null))
      .finally(() => setLoading(false));
  }, [pid, bench, win]);

  const m = a?.metrics;

  return (
    <div className="mt-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted">
          Risk &amp; return analytics
        </h2>
        <div className="flex items-center gap-2">
          <select
            value={bench ?? ""}
            onChange={(e) => setBench(Number(e.target.value))}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
          >
            {benches.map((b) => (
              <option key={b.id} value={b.id}>
                vs {b.name}
              </option>
            ))}
          </select>
          <select
            value={win}
            onChange={(e) => setWin(e.target.value)}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
          >
            {WINDOWS.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </div>
      </div>

      {m ? (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            <Metric label="Ann. return" value={pct(m.ann_return)} cls={tone(m.ann_return)} />
            <Metric label="Ann. volatility" value={pct(m.ann_vol)} />
            <Metric label="Sharpe" value={num(m.sharpe)} cls={tone(m.sharpe)} />
            <Metric label="Beta" value={num(m.beta)} />
            <Metric label="Alpha (ann.)" value={pct(m.alpha_ann)} cls={tone(m.alpha_ann)} />
            <Metric label="Correlation" value={num(m.correlation)} />
            <Metric label="Active return" value={pct(m.active_return)} cls={tone(m.active_return)} />
            <Metric label="Tracking error" value={pct(m.tracking_error)} />
            <Metric
              label="Information ratio"
              value={num(m.information_ratio)}
              cls={tone(m.information_ratio)}
            />
            <Metric label="Hit ratio" value={pct(m.hit_ratio)} />
            <Metric label="Batting avg" value={pct(m.batting_average)} />
            <Metric label="Slugging ratio" value={num(m.slugging_ratio)} />
            <Metric label="Bench ann. return" value={pct(m.bench_ann_return)} />
            <Metric label="Bench volatility" value={pct(m.bench_ann_vol)} />
            <Metric label="Bench Sharpe" value={num(m.bench_sharpe)} />
          </div>
          <p className="mt-2 text-xs text-muted">
            {a?.n_days} daily obs · {a?.start_date} → {a?.end_date} · benchmark {a?.benchmark?.name}
            {a?.benchmark?.currency ? ` (${a.benchmark.currency})` : ""} · rf = 0 · latest weights
            held constant over the window.
          </p>
        </>
      ) : (
        <p className="mt-3 text-sm text-muted">
          {loading ? "Computing…" : a?.warning ?? "Select a benchmark to compute analytics."}
        </p>
      )}
      {a?.warning && m && (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          ⚠ {a.warning}
        </p>
      )}
    </div>
  );
}
