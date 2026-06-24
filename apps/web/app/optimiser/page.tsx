"use client";

import { useCallback, useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type Sol = Schemas["OptSolutionSummary"];
type SolDetail = Schemas["OptSolutionDetail"];
type FactorSummary = Schemas["FactorSummary"];

const METHODS = [
  { key: "min_variance", label: "Minimum variance" },
  { key: "max_sharpe", label: "Maximum Sharpe" },
];
const UNIVERSES = ["sp500", "ibov", "ibx"];

type HoldoutStats = {
  total_return?: number | null;
  sharpe?: number | null;
  ann_vol?: number | null;
};
type HoldoutBlock = {
  start_date?: string;
  end_date?: string;
  n_days?: number;
  strategy?: HoldoutStats;
  equal_weight?: HoldoutStats;
};

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

export default function OptimiserPage() {
  const [sols, setSols] = useState<Sol[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<SolDetail | null>(null);
  const [method, setMethod] = useState("min_variance");
  const [universe, setUniverse] = useState("sp500");
  const [covMethod, setCovMethod] = useState("shrinkage");  // risk model: shrinkage | sample
  const [maxWeight, setMaxWeight] = useState("");  // % per position; blank = unconstrained
  const [factors, setFactors] = useState<FactorSummary[]>([]);
  const [tiltFactor, setTiltFactor] = useState("");  // blank = no tilt
  const [tiltStrength, setTiltStrength] = useState("0.0005");
  const [holdout, setHoldout] = useState("63");  // trading days; blank/0 = no holdout score
  const [savePortfolio, setSavePortfolio] = useState(false);
  const [savedPid, setSavedPid] = useState<number | null>(null);
  const [solveError, setSolveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // tilt factor menu = the signals catalog (Q9.4 — signals consumable by the optimiser)
    fetch("/api/signals/factors", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((d: FactorSummary[]) => setFactors(d))
      .catch(() => setFactors([]));
  }, []);

  const load = useCallback(() => {
    fetch("/api/optimiser/solutions", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Sol[]) => {
        setSols(d);
        if (sel == null && d[0]) setSel(d[0].solution_id);
      })
      .catch(() => setSols([]));
  }, [sel]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (sel == null) return;
    fetch(`/api/optimiser/solutions/${sel}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: SolDetail) => setDetail(d))
      .catch(() => setDetail(null));
  }, [sel]);

  async function solve() {
    setSolveError(null);
    setSavedPid(null);
    const body: Record<string, unknown> = { universe, method, n: 40, lookback: 315, cov_method: covMethod };
    if (maxWeight.trim() !== "") {
      const cap = Number(maxWeight);
      if (!Number.isFinite(cap) || cap <= 0 || cap > 100) {
        setSolveError(`"${maxWeight}" is not a valid max position % — leave blank for none`);
        return;
      }
      body.max_weight = cap / 100;
    }
    if (tiltFactor) {
      const strength = Number(tiltStrength);
      if (!Number.isFinite(strength) || strength <= 0) {
        setSolveError(`"${tiltStrength}" is not a valid tilt strength (> 0)`);
        return;
      }
      body.signal_tilt = { factor: tiltFactor, strength };
    }
    const hd = holdout.trim() === "" ? 0 : Number(holdout);
    if (!Number.isInteger(hd) || hd < 0) {
      setSolveError(`"${holdout}" is not a valid holdout day count`);
      return;
    }
    body.holdout_days = hd;
    body.save_portfolio = savePortfolio;
    setBusy(true);
    try {
      const res = await fetch("/api/optimiser/solve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then((r) => r.json());
      if (res.ok) {
        setSel(res.solution_id);
        setSavedPid(res.portfolio_id ?? null);
        load();
      } else {
        const msg = res.error ?? res.detail ?? res;
        setSolveError(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
    } catch {
      setSolveError("solve request failed (network or server error)");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">optimiser</h1>
      <p className="mt-1 text-sm text-muted">
        Constrained mean-variance optimisation (long-only, fully invested, optional per-position
        cap) over the largest names of a universe, from sym&apos;s daily-return covariance — with
        an optional signal tilt (any signals factor biases the objective) and out-of-sample
        candidate scoring: a trailing holdout is carved OUT of the covariance window and the
        solution is scored there via the backtest engine. Expected return/vol annualised, rf = 0;
        expected stats are in-sample and optimistic by construction — the holdout score is the
        honest number.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {METHODS.map((m) => (
            <option key={m.key} value={m.key}>
              {m.label}
            </option>
          ))}
        </select>
        <select
          value={covMethod}
          onChange={(e) => setCovMethod(e.target.value)}
          title="Risk model: Ledoit-Wolf shrinkage (recommended) or the raw sample covariance"
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          <option value="shrinkage">Ledoit-Wolf shrinkage</option>
          <option value="sample">sample covariance</option>
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
        <input
          value={maxWeight}
          onChange={(e) => setMaxWeight(e.target.value)}
          placeholder="max position % (blank = none)"
          className="w-52 rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        />
        <select
          value={tiltFactor}
          onChange={(e) => setTiltFactor(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          <option value="">no signal tilt</option>
          {factors.map((f) => (
            <option key={f.factor_key} value={f.factor_key}>
              tilt: {f.name}
            </option>
          ))}
        </select>
        {tiltFactor && (
          <input
            value={tiltStrength}
            onChange={(e) => setTiltStrength(e.target.value)}
            placeholder="strength"
            className="w-24 rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
          />
        )}
        <input
          value={holdout}
          onChange={(e) => setHoldout(e.target.value)}
          placeholder="holdout days"
          className="w-28 rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        />
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input
            type="checkbox"
            checked={savePortfolio}
            onChange={(e) => setSavePortfolio(e.target.checked)}
          />
          Save as portfolio
        </label>
        <button
          onClick={solve}
          disabled={busy}
          className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20 disabled:opacity-50"
        >
          {busy ? "Solving…" : "Solve"}
        </button>
        {savedPid != null && (
          <a href={`/portfolios/${savedPid}`} className="text-sm text-fg underline">
            → saved as portfolio #{savedPid}
          </a>
        )}
      </div>
      {solveError && (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          ⚠ {solveError}
        </p>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[16rem_1fr]">
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-border">
              {sols.map((s) => (
                <tr
                  key={s.solution_id}
                  onClick={() => setSel(s.solution_id)}
                  className={`cursor-pointer ${sel === s.solution_id ? "bg-fg/10" : "hover:bg-fg/5"}`}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-fg">
                      {s.method} · {s.universe_id}
                    </div>
                    <div className="text-xs text-muted">
                      {s.n_assets} assets · Sharpe {s.sharpe?.toFixed(2) ?? "—"}
                    </div>
                  </td>
                </tr>
              ))}
              {sols.length === 0 && (
                <tr>
                  <td className="px-3 py-6 text-center text-muted">No solutions yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          {detail ? (
            <>
              <div className="text-sm font-medium text-fg">
                {detail.method} · {detail.universe_id} · {detail.n_assets} assets ·{" "}
                {detail.lookback_days}d lookback
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  ["Exp. return", pct(detail.exp_return)],
                  ["Exp. vol", pct(detail.exp_vol)],
                  ["Sharpe", detail.sharpe?.toFixed(2) ?? "—"],
                  ["EW vol (bench)", pct(detail.ew_vol)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-border bg-bg px-3 py-2">
                    <div className="text-[11px] uppercase tracking-wide text-muted">{k}</div>
                    <div className="mt-0.5 text-lg font-semibold tabular-nums text-fg">{v}</div>
                  </div>
                ))}
              </div>
              {detail.method === "min_variance" &&
                detail.exp_vol != null &&
                detail.ew_vol != null && (
                  <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
                    ✓ optimised vol {pct(detail.exp_vol)} ≤ equal-weight vol {pct(detail.ew_vol)}
                  </p>
                )}
              {detail.spec && (() => {
                const sm = detail.summary as
                  | { cov_method?: string | null; shrink_delta?: number | null }
                  | null
                  | undefined;
                const cov = detail.spec.cov_method ?? sm?.cov_method;
                const delta = sm?.shrink_delta;
                return (
                  <p className="mt-2 text-xs text-muted">
                    spec: {detail.spec.max_weight != null
                      ? `cap ${parseFloat((detail.spec.max_weight * 100).toFixed(1))}% · `
                      : ""}
                    {cov
                      ? `${cov === "shrinkage" ? "Ledoit-Wolf" : "sample"} cov${
                          cov === "shrinkage" && delta != null ? ` (δ ${delta.toFixed(2)})` : ""
                        } · `
                      : ""}
                    {detail.spec.signal_tilt
                      ? `tilt ${detail.spec.signal_tilt.factor} ×${detail.spec.signal_tilt.strength} · `
                      : ""}
                    train {detail.spec.train_start} → {detail.spec.train_end}
                  </p>
                );
              })()}
              {(() => {
                const h = detail.summary?.holdout as HoldoutBlock | null | undefined;
                if (!h?.strategy) return null;
                return (
                  <div className="mt-3 rounded-lg border border-border bg-bg px-3 py-2">
                    <div className="text-[11px] uppercase tracking-wide text-muted">
                      Out-of-sample holdout ({h.start_date} → {h.end_date}, scored via backtest)
                    </div>
                    <div className="mt-1 grid grid-cols-2 gap-x-4 text-sm">
                      <span className="text-muted">
                        solution: <span className="tabular-nums text-fg">{pct(h.strategy.total_return)}</span>
                        {" · Sharpe "}
                        <span className="tabular-nums text-fg">{h.strategy.sharpe?.toFixed(2) ?? "—"}</span>
                      </span>
                      <span className="text-muted">
                        equal-wt: <span className="tabular-nums text-fg">{pct(h.equal_weight?.total_return)}</span>
                        {" · Sharpe "}
                        <span className="tabular-nums text-fg">{h.equal_weight?.sharpe?.toFixed(2) ?? "—"}</span>
                      </span>
                    </div>
                  </div>
                );
              })()}

              <h2 className="mt-5 text-sm font-medium uppercase tracking-wide text-muted">
                Weights ({detail.weights.length})
              </h2>
              <div className="mt-2 overflow-hidden rounded-xl border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-surface text-left text-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">Ticker</th>
                      <th className="px-3 py-2 text-right font-medium">Weight</th>
                      <th className="px-3 py-2 font-medium">Allocation</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {detail.weights.map((w) => (
                      <tr key={w.figi} className="hover:bg-fg/5">
                        <td className="px-3 py-1.5 font-medium text-fg">{w.ticker ?? w.figi}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-fg">
                          {(w.weight * 100).toFixed(1)}%
                        </td>
                        <td className="px-3 py-1.5">
                          <div
                            className="h-2 rounded bg-sky-500"
                            style={{ width: `${Math.min(100, w.weight * 100 * 3)}%` }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted">Select or solve a portfolio.</p>
          )}
        </div>
      </div>
    </div>
  );
}
