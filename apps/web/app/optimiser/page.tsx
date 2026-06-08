"use client";

import { useCallback, useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type Sol = Schemas["OptSolutionSummary"];
type SolDetail = Schemas["OptSolutionDetail"];

const METHODS = [
  { key: "min_variance", label: "Minimum variance" },
  { key: "max_sharpe", label: "Maximum Sharpe" },
];
const UNIVERSES = ["sp500", "ibov", "ibx"];

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

export default function OptimiserPage() {
  const [sols, setSols] = useState<Sol[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<SolDetail | null>(null);
  const [method, setMethod] = useState("min_variance");
  const [universe, setUniverse] = useState("sp500");
  const [busy, setBusy] = useState(false);

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
    setBusy(true);
    const res = await fetch("/api/optimiser/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ universe, method, n: 40, lookback: 252 }),
    }).then((r) => r.json());
    setBusy(false);
    if (res.ok) {
      setSel(res.solution_id);
      load();
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">optimiser</h1>
      <p className="mt-1 text-sm text-muted">
        Mean-variance portfolio optimisation (long-only, fully invested) over the largest names of a
        universe, from sym&apos;s daily-return covariance. Expected return/vol annualised, rf = 0.
        In-sample optimisation — expected stats are optimistic by construction.
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
          onClick={solve}
          disabled={busy}
          className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20 disabled:opacity-50"
        >
          {busy ? "Solving…" : "Solve"}
        </button>
      </div>

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
