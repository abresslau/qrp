"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Schemas } from "@/lib/api";
import { dateAxisTicks, tickAnchor } from "@/lib/date-axis";

type RunSummary = Schemas["RunSummary"];
type RunDetail = Schemas["RunDetail"];
type Stats = Schemas["Stats"];
type FactorSummary = Schemas["FactorSummary"];

const UNIVERSES = ["sp500", "ibov", "ibx"];
const WEIGHTINGS = ["equal", "cap"] as const;
const REBALANCES = ["monthly", "quarterly"] as const;

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}
function num(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

function EquityCurve({ detail }: { detail: RunDetail }) {
  const { sPath, bPath, xticks, hi } = useMemo(() => {
    const pts = detail.curve;
    if (pts.length < 2) return { sPath: "", bPath: "", xticks: [], hi: 0 };
    const W = 760;
    const H = 260;
    const PAD = 30;
    const xs = pts.map((p) => new Date(p.obs_date).getTime());
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
    const xticks = dateAxisTicks(minX, maxX, 6).map((tk) => ({ x: sx(tk.t), label: tk.label }));
    return { sPath: mk((p) => p.strat), bPath: mk((p) => p.base), xticks, hi: maxY };
  }, [detail]);

  if (detail.curve.length < 2) return <p className="text-sm text-muted">No curve.</p>;
  return (
    <div>
      <svg viewBox="0 0 760 260" className="w-full">
        <path d={bPath} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-muted" />
        <path d={sPath} fill="none" stroke="currentColor" strokeWidth={2} className="text-sky-500" />
        {xticks.map((t, i) => (
          <text key={i} x={t.x} y={252} textAnchor={tickAnchor(i)} className="fill-muted" fontSize={10}>
            {t.label}
          </text>
        ))}
      </svg>
      <div className="text-center text-xs text-muted">
        <span className="text-sky-500">strategy</span> vs baseline · peak ×{hi.toFixed(2)}
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
  const [factors, setFactors] = useState<FactorSummary[]>([]);
  const [factor, setFactor] = useState("mom_12_1");
  const [universe, setUniverse] = useState("sp500");
  const [weighting, setWeighting] = useState<string>("equal");
  const [rebalance, setRebalance] = useState<string>("monthly");
  const [topN, setTopN] = useState<string>("");  // empty = top quintile (top_pct 0.2)
  const [busy, setBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [savePortfolio, setSavePortfolio] = useState(false);
  const [savedPid, setSavedPid] = useState<number | null>(null);

  useEffect(() => {
    // the strategy's factor menu IS the signals catalog (Q9.4) — incl. cross-module factors
    fetch("/api/signals/factors", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((d: FactorSummary[]) => setFactors(d))
      .catch(() => setFactors([]));
  }, []);

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
    setSavedPid(null);
    setRunError(null);
    let selection: { top_n: number } | { top_pct: number };
    if (topN.trim() === "") {
      selection = { top_pct: 0.2 };
    } else {
      const n = Number(topN);
      if (!Number.isInteger(n) || n <= 0) {
        // never silently run a different strategy than the operator typed
        setRunError(`"${topN}" is not a valid top N — leave blank for the top quintile`);
        return;
      }
      selection = { top_n: n };
    }
    setBusy(true);
    try {
      const res = await fetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          factor, universe, weighting, rebalance, ...selection,
          save_portfolio: savePortfolio,
        }),
      }).then((r) => r.json());
      if (res.ok) {
        setSel(res.run_id);
        setSavedPid(res.portfolio_id ?? null);
        loadRuns();
      } else {
        // engine refusals carry `error`; router 422s carry `detail` / an error envelope
        const msg = res.error ?? res.detail ?? res;
        setRunError(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
    } catch {
      setRunError("run request failed (network or server error)");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">backtest</h1>
      <p className="mt-1 text-sm text-muted">
        Walk-forward strategy from a reproducible spec: any signals factor (including
        cross-module ones), top-quintile or top-N selection, equal- or cap-weighted, rebalanced
        monthly or quarterly, vs an equal-weight-of-roster baseline. The factor is recomputed
        through the signals package at each rebalance date (no look-ahead); returns tie to
        fact_returns. Sparse factors that can&apos;t cover a universe fail honestly.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select
          value={factor}
          onChange={(e) => setFactor(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {(factors.length
            ? factors.map((f) => ({ key: f.factor_key, label: f.name }))
            : [{ key: "mom_12_1", label: "12-1 Momentum" }]
          ).map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </select>
        <select
          value={weighting}
          onChange={(e) => setWeighting(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {WEIGHTINGS.map((w) => (
            <option key={w} value={w}>
              {w === "equal" ? "equal-weight" : "cap-weight"}
            </option>
          ))}
        </select>
        <select
          value={rebalance}
          onChange={(e) => setRebalance(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {REBALANCES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <input
          value={topN}
          onChange={(e) => setTopN(e.target.value)}
          placeholder="top N (blank = quintile)"
          className="w-40 rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        />
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
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input
            type="checkbox"
            checked={savePortfolio}
            onChange={(e) => setSavePortfolio(e.target.checked)}
          />
          Save as portfolio
        </label>
        <button
          onClick={run}
          disabled={busy}
          className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20 disabled:opacity-50"
        >
          {busy ? "Running…" : "Run backtest"}
        </button>
        {savedPid != null && (
          <a href={`/portfolios/${savedPid}`} className="text-sm text-fg underline">
            → saved as portfolio #{savedPid}
          </a>
        )}
      </div>
      {runError && (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          ⚠ {runError}
        </p>
      )}

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
                      {r.spec
                        ? `${r.spec.top_n != null ? `top ${r.spec.top_n}` : `top ${((r.spec.top_pct ?? 0) * 100).toFixed(0)}%`} · ${r.spec.weighting} · ${r.spec.rebalance} · `
                        : ""}
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
