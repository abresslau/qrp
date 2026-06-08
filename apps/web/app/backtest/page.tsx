"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Schemas } from "@/lib/api";

type RunSummary = Schemas["RunSummary"];
type RunDetail = Schemas["RunDetail"];
type Stats = Schemas["Stats"];

const FACTORS = [
  { key: "mom_12_1", label: "12-1 Momentum" },
  { key: "vol_1y", label: "Low Volatility" },
  { key: "size", label: "Size (small)" },
];
const UNIVERSES = ["sp500", "ibov", "ibx"];

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}
function num(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

function EquityCurve({ detail }: { detail: RunDetail }) {
  const { sPath, bPath, x0, x1, hi } = useMemo(() => {
    const pts = detail.curve;
    if (pts.length < 2) return { sPath: "", bPath: "", x0: "", x1: "", hi: 0 };
    const W = 760;
    const H = 260;
    const PAD = 30;
    const xs = pts.map((p) => new Date(p.date).getTime());
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const allY = pts.flatMap((p) => [p.strat, p.base]);
    const minY = Math.min(...allY);
    const maxY = Math.max(...allY);
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const sx = (t: number) => PAD + ((t - minX) / spanX) * (W - 2 * PAD);
    const sy = (v: number) => H - PAD - ((v - minY) / spanY) * (H - 2 * PAD);
    const mk = (sel: (p: RunDetail["curve"][number]) => number) =>
      pts.map((p, i) => `${i ? "L" : "M"}${sx(xs[i]).toFixed(1)},${sy(sel(p)).toFixed(1)}`).join(" ");
    return {
      sPath: mk((p) => p.strat),
      bPath: mk((p) => p.base),
      x0: new Date(minX).toLocaleDateString(),
      x1: new Date(maxX).toLocaleDateString(),
      hi: maxY,
    };
  }, [detail]);

  if (detail.curve.length < 2) return <p className="text-sm text-muted">No curve.</p>;
  return (
    <div>
      <svg viewBox="0 0 760 260" className="w-full">
        <path d={bPath} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-muted" />
        <path d={sPath} fill="none" stroke="currentColor" strokeWidth={2} className="text-sky-500" />
      </svg>
      <div className="flex justify-between text-xs text-muted">
        <span>{x0}</span>
        <span>
          <span className="text-sky-500">strategy</span> vs baseline · peak ×{hi.toFixed(2)}
        </span>
        <span>{x1}</span>
      </div>
    </div>
  );
}

function StatBlock({ title, s, accent }: { title: string; s: Stats; accent?: boolean }) {
  return (
    <div className={`rounded-lg border border-border p-3 ${accent ? "bg-sky-500/5" : "bg-bg"}`}>
      <div className="text-xs uppercase tracking-wide text-muted">{title}</div>
      <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-sm">
        <span className="text-muted">Total</span>
        <span className="text-right tabular-nums text-fg">{pct(s.total_return)}</span>
        <span className="text-muted">Ann. return</span>
        <span className="text-right tabular-nums text-fg">{pct(s.ann_return)}</span>
        <span className="text-muted">Ann. vol</span>
        <span className="text-right tabular-nums text-fg">{pct(s.ann_vol)}</span>
        <span className="text-muted">Sharpe</span>
        <span className="text-right tabular-nums text-fg">{num(s.sharpe)}</span>
        <span className="text-muted">Max DD</span>
        <span className="text-right tabular-nums text-fg">{pct(s.max_drawdown)}</span>
      </div>
    </div>
  );
}

export default function BacktestPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [factor, setFactor] = useState("mom_12_1");
  const [universe, setUniverse] = useState("sp500");
  const [busy, setBusy] = useState(false);

  const loadRuns = useCallback(() => {
    fetch("/api/backtest/runs", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: RunSummary[]) => {
        setRuns(d);
        if (sel == null && d[0]) setSel(d[0].run_id);
      })
      .catch(() => setRuns([]));
  }, [sel]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (sel == null) return;
    fetch(`/api/backtest/runs/${sel}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: RunDetail) => setDetail(d))
      .catch(() => setDetail(null));
  }, [sel]);

  async function run() {
    setBusy(true);
    const res = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ factor, universe, top_pct: 0.2 }),
    }).then((r) => r.json());
    setBusy(false);
    if (res.ok) {
      setSel(res.run_id);
      loadRuns();
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">backtest</h1>
      <p className="mt-1 text-sm text-muted">
        Walk-forward factor strategy: equal-weight the top quintile by a signal factor, rebalanced
        monthly, vs an equal-weight-universe baseline. The factor is recomputed from sym at each
        rebalance date (no look-ahead); returns tie to fact_returns.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select
          value={factor}
          onChange={(e) => setFactor(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {FACTORS.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
        <select
          value={universe}
          onChange={(e) => setUniverse(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {UNIVERSES.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
        <button
          onClick={run}
          disabled={busy}
          className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20 disabled:opacity-50"
        >
          {busy ? "Running…" : "Run backtest"}
        </button>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[16rem_1fr]">
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-border">
              {runs.map((r) => (
                <tr
                  key={r.run_id}
                  onClick={() => setSel(r.run_id)}
                  className={`cursor-pointer ${sel === r.run_id ? "bg-fg/10" : "hover:bg-fg/5"}`}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-fg">
                      {r.factor} · {r.universe_id}
                    </div>
                    <div className="text-xs text-muted">
                      {r.n_rebalances} rebals · {r.n_days}d ·{" "}
                      {pct(r.summary?.strategy?.ann_return)} ann
                    </div>
                  </td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr>
                  <td className="px-3 py-6 text-center text-muted">No runs yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          {detail && detail.summary ? (
            <>
              <div className="text-sm font-medium text-fg">
                {detail.factor} top-20% · {detail.universe_id} · {detail.start_date} →{" "}
                {detail.end_date}
              </div>
              <div className="mt-3">
                <EquityCurve detail={detail} />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <StatBlock title="Strategy" s={detail.summary.strategy} accent />
                <StatBlock title="Baseline (EW universe)" s={detail.summary.baseline} />
              </div>
              <p className="mt-3 text-xs text-muted">
                Excess total return {pct(detail.summary.excess_total)} · first rebalance held{" "}
                {detail.summary.first_holding_n} names. rf = 0; monthly rebalance; coverage-gated start.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">Select or run a backtest.</p>
          )}
        </div>
      </div>
    </div>
  );
}
