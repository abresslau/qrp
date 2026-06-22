"use client";

// Live index-close fidelity panel for the Validation page: re-fetches each benchmark index's
// official close from the source and compares it to the latest stored level (the same check as
// `sym index-reconcile` / the nightly EOD drift monitor). Network-dependent (a few seconds), so it
// loads in this client panel without blocking the server-rendered runs table above it.

import { useCallback, useEffect, useState } from "react";

type Reconcile = {
  status: string; // pass | warn | fail
  checked: number;
  warnings: number;
  failures: number;
  samples: string[];
  detail: string | null;
};

function pill(status: string): string {
  if (status === "fail")
    return "bg-rose-500/10 text-rose-700 ring-rose-600/20 dark:text-rose-400 dark:ring-rose-500/30";
  if (status === "warn")
    return "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-400 dark:ring-amber-500/30";
  return "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-400 dark:ring-emerald-500/30";
}

export function IndexReconcilePanel() {
  const [data, setData] = useState<Reconcile | null>(null);
  const [error, setError] = useState<string | null>(null);
  // loading starts true; state is only set inside the async callbacks (never synchronously in the
  // mount effect) so this doesn't trip react-hooks/set-state-in-effect.
  const [loading, setLoading] = useState(true);
  const [runId, setRunId] = useState(0); // newest-wins guard

  const fetchData = useCallback((id: number) => {
    fetch("/api/sym/indices/reconcile", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`reconcile -> ${r.status}`))))
      .then((d: Reconcile) => {
        setRunId((cur) => {
          if (id === cur) {
            setData(d);
            setError(null);
            setLoading(false);
          }
          return cur;
        });
      })
      .catch((e) =>
        setRunId((cur) => {
          if (id === cur) {
            setError(String(e));
            setLoading(false);
          }
          return cur;
        }),
      );
  }, []);

  useEffect(() => {
    fetchData(0);
  }, [fetchData]);

  function refresh() {
    const id = runId + 1;
    setRunId(id);
    setLoading(true);
    setError(null);
    fetchData(id);
  }

  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-fg">Index close fidelity</h2>
          <p className="mt-0.5 text-sm text-muted">
            Stored latest index level vs the source&apos;s official close (live). Drift is a vendor
            candle-vs-settled gap — see <code className="font-mono">sym index-reconcile</code>.
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="rounded-md border border-border px-2.5 py-1 text-xs text-muted hover:bg-fg/5 hover:text-fg disabled:opacity-50"
        >
          {loading ? "Checking…" : "Re-check"}
        </button>
      </div>

      <div className="mt-3 rounded-xl border border-border bg-surface p-4">
        {loading && data == null ? (
          <p className="text-sm text-muted">Reconciling against the source… (a few seconds)</p>
        ) : error ? (
          <p className="text-sm text-rose-500">Could not reconcile: {error}</p>
        ) : data ? (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${pill(data.status)}`}>
                {data.status.toUpperCase()}
              </span>
              <span className="tabular-nums text-muted">
                {data.checked} checked · <span className="text-amber-600 dark:text-amber-400">{data.warnings} warn</span>{" "}
                · <span className="text-rose-600 dark:text-rose-400">{data.failures} fail</span>
              </span>
              {data.detail ? <span className="text-xs text-muted">{data.detail}</span> : null}
            </div>
            {data.samples.length > 0 ? (
              <ul className="mt-3 space-y-1 text-xs">
                {data.samples.map((s, i) => (
                  <li key={i} className="font-mono text-muted">
                    {s}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-xs text-muted">All indices match the source official close.</p>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}
