"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Schemas } from "@/lib/api";
import { axisTickCount, dateAxisTicks, tickAnchor } from "@/lib/date-axis";

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
// 0..1 probability → unsigned percent (DSR / PBO), distinct from the signed-return `pct`.
function prob(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

// Sweep / overfitting verdict shapes. Local types (not Schemas) — the sweep models post-date the
// last api-types regen, which needs a live API restart; mirrors how the rates page carries local
// types until the generated ones catch up.
type SweepVerdict = {
  n_configs: number;
  n_runnable: number;
  n_common_days: number;
  actual_years: number;
  sigma_sr: number;
  deflated_sharpe: {
    dsr: number | null;
    sharpe_ann: number;
    sr_benchmark: number;
    n_obs: number;
    n_trials: number;
  } | null;
  pbo: { pbo: number | null; n_splits: number; n_combos: number } | null;
  min_btl_years: number | null;
  min_btl_satisfied: boolean;
  best: { config: Record<string, unknown>; run_id: number | null; sharpe_ann: number } | null;
  verdict_credible: boolean;
};
type SweepSummary = {
  sweep_id: number;
  created_at: string | null;
  base_spec: Record<string, unknown> | null;
  grid: Record<string, unknown> | null;
  n_configs: number;
  best_run_id: number | null;
  summary: SweepVerdict | null;
};

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
    const xticks = dateAxisTicks(minX, maxX, axisTickCount(W - 2 * PAD)).map((tk) => ({ x: sx(tk.t), label: tk.label }));
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

type Summary = Schemas["Summary"];

/** Credibility strip: turnover + transaction cost + the spread t-stat vs the t>3.0 hurdle. */
function SignificanceBar({ summary }: { summary: Summary }) {
  const t = summary.spread_tstat;
  const hurdle = summary.spread_tstat_hurdle ?? 3.0;
  const sig = summary.spread_significant ?? false;
  const costed = (summary.cost_bps ?? 0) > 0;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
      <span
        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-medium tabular-nums ${
          sig
            ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : "bg-fg/5 text-muted"
        }`}
        title="Spread (strategy − baseline) t-stat vs the Harvey-Liu-Zhu multiple-testing hurdle of 3.0 (not the naive 2.0)"
      >
        {sig ? "✓" : "○"} spread t = {t == null ? "—" : t.toFixed(2)}
        <span className="text-muted">vs {hurdle.toFixed(1)} hurdle</span>
      </span>
      {summary.turnover_ann != null && (
        <span className="text-muted">
          turnover{" "}
          <span className="tabular-nums text-fg">{(summary.turnover_ann * 100).toFixed(0)}%/yr</span>
        </span>
      )}
      <span className="text-muted">
        {costed ? (
          <>
            net of <span className="tabular-nums text-fg">{summary.cost_bps}bps</span> · drag{" "}
            <span className="tabular-nums text-fg">{pct(summary.cost_drag_total)}</span>
            {summary.strategy_gross?.total_return != null && (
              <>
                {" "}· gross{" "}
                <span className="tabular-nums text-fg">{pct(summary.strategy_gross.total_return)}</span>
              </>
            )}
          </>
        ) : (
          "gross (no transaction costs)"
        )}
      </span>
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

/** Overfitting verdict for a parameter sweep: Deflated Sharpe, PBO (CSCV), MinBTL — the
 * selection-bias defence over N trials. Reads the persisted sweep summary. */
function SweepVerdict({
  sweep,
  onViewRun,
}: {
  sweep: SweepSummary;
  onViewRun: (runId: number) => void;
}) {
  const s = sweep.summary;
  if (!s) return <p className="text-sm text-muted">This sweep has no verdict.</p>;
  const dsr = s.deflated_sharpe?.dsr ?? null;
  const pboV = s.pbo?.pbo ?? null;
  const credible = s.verdict_credible;
  const bestCfg = s.best?.config ?? {};
  const cfgStr = Object.entries(bestCfg)
    .map(([k, v]) => `${k === "universe_id" ? "universe" : k}=${String(v)}`)
    .join(" · ");
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${
            credible
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "bg-amber-500/10 text-amber-700 dark:text-amber-300"
          }`}
          title="Credible only if the best config's Deflated Sharpe > 0.95 AND PBO ≤ 0.05"
        >
          {credible ? "✓ survives multiple-testing" : "○ not credible (likely overfit/under-powered)"}
        </span>
        <span className="text-xs text-muted">
          N = <span className="tabular-nums text-fg">{sweep.n_configs}</span> configs
          {s.n_runnable !== sweep.n_configs ? ` (${s.n_runnable} ran)` : ""} ·{" "}
          <span className="tabular-nums text-fg">{s.n_common_days}</span> common days
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-bg p-3">
          <div className="text-xs uppercase tracking-wide text-muted" title="P(true Sharpe beats the expected best-of-N luck), skew/kurtosis-corrected">
            Deflated Sharpe
          </div>
          <div className="mt-1 text-lg font-medium tabular-nums text-fg">{prob(dsr)}</div>
          <div className="text-xs text-muted">
            {dsr == null ? "undefined" : dsr > 0.95 ? "> 0.95 ✓" : "≤ 0.95"} · best SR{" "}
            <span className="tabular-nums">{num(s.deflated_sharpe?.sharpe_ann)}</span>
          </div>
        </div>
        <div className="rounded-lg border border-border bg-bg p-3">
          <div className="text-xs uppercase tracking-wide text-muted" title="Probability of Backtest Overfitting (CSCV): rate the in-sample-best lands below the out-of-sample median">
            PBO
          </div>
          <div className="mt-1 text-lg font-medium tabular-nums text-fg">{prob(pboV)}</div>
          <div className="text-xs text-muted">
            {pboV == null ? "undefined" : pboV <= 0.05 ? "≤ 0.05 ✓" : "> 0.05 reject"} ·{" "}
            {s.pbo?.n_combos ?? 0} splits
          </div>
        </div>
        <div className="rounded-lg border border-border bg-bg p-3">
          <div className="text-xs uppercase tracking-wide text-muted" title="Minimum Backtest Length: years of history N trials demand before an in-sample Sharpe is evidence, not luck">
            MinBTL
          </div>
          <div className="mt-1 text-lg font-medium tabular-nums text-fg">
            {s.min_btl_years == null ? "—" : `${s.min_btl_years.toFixed(1)}y`}
          </div>
          <div className="text-xs text-muted">
            have {s.actual_years.toFixed(1)}y ·{" "}
            {s.min_btl_satisfied ? "enough ✓" : "too short"}
          </div>
        </div>
      </div>
      {s.best && (
        <p className="mt-3 text-xs text-muted">
          Best config: <span className="text-fg">{cfgStr || "(base)"}</span>
          {s.best.run_id != null && (
            <>
              {" "}·{" "}
              <button
                type="button"
                onClick={() => onViewRun(s.best!.run_id!)}
                className="text-fg underline"
              >
                view run #{s.best.run_id}
              </button>
            </>
          )}
        </p>
      )}
      <p className="mt-1 text-xs text-muted">
        N = full grid size (conservative; correlated configs only raise the hurdle). Harvey-Liu-Zhu
        t&gt;3 · Bailey-López de Prado DSR/PBO/MinBTL.
      </p>
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
  const [costBps, setCostBps] = useState<string>("10");  // one-way bps; 0 = gross
  const [busy, setBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [savePortfolio, setSavePortfolio] = useState(false);
  const [savedPid, setSavedPid] = useState<number | null>(null);
  // parameter sweep (overfitting verdict)
  const [sweeps, setSweeps] = useState<SweepSummary[]>([]);
  const [selSweep, setSelSweep] = useState<number | null>(null);
  const [gridTopPct, setGridTopPct] = useState("0.1,0.2,0.3");
  const [gridRebal, setGridRebal] = useState<Set<string>>(new Set(["monthly", "quarterly"]));
  const [sweepBusy, setSweepBusy] = useState(false);
  const [sweepError, setSweepError] = useState<string | null>(null);

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

  const loadSweeps = useCallback(() => {
    fetch("/api/backtest/sweeps", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((d: SweepSummary[]) => {
        setSweeps(d);
        if (selSweep == null && d[0]) setSelSweep(d[0].sweep_id);
      })
      .catch(() => setSweeps([]));
  }, [selSweep]);

  useEffect(() => {
    loadSweeps();
  }, [loadSweeps]);

  async function runSweep() {
    setSweepError(null);
    const topPcts = gridTopPct
      .split(",")
      .map((x) => Number(x.trim()))
      .filter((x) => Number.isFinite(x) && x > 0 && x < 1);
    const rebal = [...gridRebal];
    if (topPcts.length === 0) {
      setSweepError("enter at least one top_pct between 0 and 1 (e.g. 0.1,0.2,0.3)");
      return;
    }
    if (rebal.length === 0) {
      setSweepError("select at least one rebalance cadence");
      return;
    }
    if (topPcts.length * rebal.length < 2) {
      setSweepError("a sweep needs ≥ 2 configurations — vary top_pct or add a cadence");
      return;
    }
    const cb = costBps.trim() === "" ? 0 : Number(costBps);
    setSweepBusy(true);
    try {
      const res = await fetch("/api/backtest/sweep", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          factor,
          universe,
          weighting,
          cost_bps: Number.isFinite(cb) && cb >= 0 ? cb : 10,
          grid: { top_pct: topPcts, rebalance: rebal },
        }),
      }).then((r) => r.json());
      if (res.ok) {
        await Promise.resolve(loadSweeps());
        if (res.sweep_id != null) setSelSweep(res.sweep_id);
      } else {
        const msg = res.error ?? res.detail ?? res;
        setSweepError(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
    } catch {
      setSweepError("sweep request failed (network or server error)");
    } finally {
      setSweepBusy(false);
    }
  }

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
    const cb = costBps.trim() === "" ? 0 : Number(costBps);
    if (!Number.isFinite(cb) || cb < 0) {
      setRunError(`"${costBps}" is not a valid cost in bps — use 0 for a gross run`);
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          factor, universe, weighting, rebalance, ...selection,
          cost_bps: cb, save_portfolio: savePortfolio,
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
        <input
          value={costBps}
          onChange={(e) => setCostBps(e.target.value)}
          placeholder="cost bps"
          title="One-way transaction cost in bps charged on turnover (0 = gross)"
          className="w-24 rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
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
                        ? `${r.spec.top_n != null ? `top ${r.spec.top_n}` : `top ${((r.spec.top_pct ?? 0) * 100).toFixed(0)}%`} · ${r.spec.weighting} · ${r.spec.rebalance}${(r.spec.cost_bps ?? 0) > 0 ? ` · ${r.spec.cost_bps}bps` : ""} · `
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
                <StatBlock
                  title={(detail.summary.cost_bps ?? 0) > 0 ? "Strategy (net of costs)" : "Strategy"}
                  s={detail.summary.strategy}
                  accent
                />
                <StatBlock title="Baseline (EW universe)" s={detail.summary.baseline} />
              </div>
              <SignificanceBar summary={detail.summary} />
              <p className="mt-3 text-xs text-muted">
                Excess total return {pct(detail.summary.excess_total)} · first rebalance held{" "}
                {detail.summary.first_holding_n} names. rf = 0; coverage-gated start.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">Select or run a backtest.</p>
          )}
        </div>
      </div>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Overfitting sweep
        </h2>
        <p className="mt-1 text-sm text-muted">
          Run the base strategy across a parameter grid and judge the whole set, not the
          best-looking single run. The grid size N feeds the Deflated Sharpe, the Probability of
          Backtest Overfitting (PBO via CSCV) and the Minimum Backtest Length — the defence against a
          sweep manufacturing a spurious winner. Base factor / universe / weighting / cost come from
          the controls above.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-sm text-muted">
            top_pct grid
            <input
              value={gridTopPct}
              onChange={(e) => setGridTopPct(e.target.value)}
              placeholder="0.1,0.2,0.3"
              title="Comma-separated top-quantile cutoffs to sweep, each between 0 and 1"
              className="w-36 rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
            />
          </label>
          {REBALANCES.map((r) => (
            <label key={r} className="flex items-center gap-1.5 text-sm text-muted">
              <input
                type="checkbox"
                checked={gridRebal.has(r)}
                onChange={(e) =>
                  setGridRebal((prev) => {
                    const next = new Set(prev);
                    if (e.target.checked) next.add(r);
                    else next.delete(r);
                    return next;
                  })
                }
              />
              {r}
            </label>
          ))}
          <span className="text-xs text-muted">
            N ={" "}
            <span className="tabular-nums text-fg">
              {gridTopPct.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0 && x < 1).length *
                gridRebal.size}
            </span>{" "}
            configs
          </span>
          <button
            onClick={runSweep}
            disabled={sweepBusy}
            className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20 disabled:opacity-50"
          >
            {sweepBusy ? "Sweeping…" : "Run sweep"}
          </button>
        </div>
        {sweepError && (
          <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            ⚠ {sweepError}
          </p>
        )}

        <div className="mt-4 grid gap-5 lg:grid-cols-[16rem_1fr]">
          <div className="overflow-hidden rounded-xl border border-border">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-border">
                {sweeps.map((sw) => (
                  <tr
                    key={sw.sweep_id}
                    onClick={() => setSelSweep(sw.sweep_id)}
                    className={`cursor-pointer ${selSweep === sw.sweep_id ? "bg-fg/10" : "hover:bg-fg/5"}`}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5 font-medium text-fg">
                        <span
                          className={
                            sw.summary?.verdict_credible
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-amber-600 dark:text-amber-400"
                          }
                        >
                          {sw.summary?.verdict_credible ? "✓" : "○"}
                        </span>
                        {String(sw.base_spec?.factor ?? "—")} · {sw.n_configs} configs
                      </div>
                      <div className="text-xs text-muted">
                        DSR {prob(sw.summary?.deflated_sharpe?.dsr)} · PBO{" "}
                        {prob(sw.summary?.pbo?.pbo)} · {sw.created_at?.slice(0, 10) ?? ""}
                      </div>
                    </td>
                  </tr>
                ))}
                {sweeps.length === 0 && (
                  <tr>
                    <td className="px-3 py-6 text-center text-muted">No sweeps yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="rounded-xl border border-border bg-surface p-4">
            {(() => {
              const selectedSweep = sweeps.find((s) => s.sweep_id === selSweep) ?? null;
              return selectedSweep ? (
                <SweepVerdict sweep={selectedSweep} onViewRun={setSel} />
              ) : (
                <p className="text-sm text-muted">Run or select a sweep to see its verdict.</p>
              );
            })()}
          </div>
        </div>
      </section>
    </div>
  );
}
