"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AnalyticsPanel } from "@/components/analytics-panel";
import type { Schemas } from "@/lib/api";

type Portfolio = Schemas["PortfolioDetail"];
type Returns = Schemas["PortfolioReturns"];
type WindowOpt = { code: string; label: string };

function pct(r: number | null | undefined): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function retClass(r: number | null | undefined): string {
  if (r == null) return "text-muted";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

export default function PortfolioDetail() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<Portfolio | null>(null);
  const [ret, setRet] = useState<Returns | null>(null);
  const [windows, setWindows] = useState<WindowOpt[]>([]);
  const [win, setWin] = useState("YTD");
  const [asOf, setAsOf] = useState("2026-06-05");
  const [csv, setCsv] = useState("");
  const [msg, setMsg] = useState("");

  const loadPortfolio = useCallback(() => {
    fetch(`/api/portfolios/${id}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Portfolio) => setP(d))
      .catch(() => setP(null));
  }, [id]);

  useEffect(() => {
    loadPortfolio();
    fetch("/api/sym/return-windows", { cache: "no-store" })
      .then((r) => r.json())
      .then((w: WindowOpt[]) => setWindows(w))
      .catch(() => setWindows([]));
  }, [loadPortfolio]);

  useEffect(() => {
    fetch(`/api/portfolios/${id}/returns?window=${win}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Returns) => setRet(d))
      .catch(() => setRet(null));
  }, [id, win, p]);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const items = csv
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const [ident, w] = l.split(/[,\t]/).map((s) => s.trim());
        return { identifier: ident, weight: Number(w) };
      })
      .filter((x) => x.identifier && !Number.isNaN(x.weight));
    if (items.length === 0) {
      setMsg("Nothing to upload — use lines like: AAPL, 0.1");
      return;
    }
    const body: Schemas["UploadWeights"] = { as_of_date: asOf, items };
    const res = await fetch(`/api/portfolios/${id}/weights`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    setMsg(`Stored ${res.stored}${res.unresolved?.length ? ` · unresolved: ${res.unresolved.join(", ")}` : ""}`);
    setCsv("");
    loadPortfolio();
  }

  if (!p) {
    return (
      <div>
        <Link href="/portfolios" className="text-sm text-muted hover:text-fg">← Portfolios</Link>
        <p className="mt-4 text-sm text-muted">Loading… (or not found)</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      <Link href="/portfolios" className="text-sm text-muted hover:text-fg">← Portfolios</Link>
      <div className="mt-2 flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">{p.name}</h1>
          <p className="mt-1 text-sm text-muted">
            {p.client ? `${p.client} · ` : ""}{p.base_currency} · {p.weights.length} holdings
            {p.latest_as_of ? ` · as of ${p.latest_as_of}` : ""}
          </p>
        </div>
      </div>

      {/* Return / PnL */}
      <div className="mt-6 rounded-xl border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs uppercase tracking-wide text-muted">Portfolio return (weighted)</div>
          <select
            value={win}
            onChange={(e) => setWin(e.target.value)}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
          >
            {windows.map((w) => (
              <option key={w.code} value={w.code}>{w.label}</option>
            ))}
          </select>
        </div>
        <div className={`mt-1 text-3xl font-semibold tabular-nums ${retClass(ret?.portfolio_return)}`}>
          {pct(ret?.portfolio_return)}
        </div>
        {ret && (
          <div className="mt-1 text-xs text-muted">
            {ret.window} · weights as of {ret.as_of ?? "—"} · coverage{" "}
            {(ret.covered_weight * 100).toFixed(0)}% of weight ({ret.n_with_return}/{ret.n_constituents}{" "}
            with returns)
            {ret.covered_weight > 0 && ret.covered_weight < 0.999
              ? ` · normalized ${pct(ret.portfolio_return_normalized)}`
              : ""}
          </div>
        )}
      </div>

      {/* Contributions */}
      {ret && ret.constituents.length > 0 && (
        <>
          <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">
            Contributions ({ret.window})
          </h2>
          <div className="mt-3 overflow-hidden rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface text-left text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Ticker</th>
                  <th className="px-4 py-2 text-right font-medium">Weight</th>
                  <th className="px-4 py-2 text-right font-medium">Return</th>
                  <th className="px-4 py-2 text-right font-medium">Contribution</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {ret.constituents.map((c) => (
                  <tr key={c.ticker} className="hover:bg-fg/5">
                    <td className="px-4 py-2 font-medium text-fg">{c.ticker}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted">
                      {(c.weight * 100).toFixed(1)}%
                    </td>
                    <td className={`px-4 py-2 text-right tabular-nums ${retClass(c.ret)}`}>{pct(c.ret)}</td>
                    <td className={`px-4 py-2 text-right tabular-nums ${retClass(c.contribution)}`}>
                      {pct(c.contribution)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Risk & return analytics */}
      <AnalyticsPanel pid={String(id)} />

      {/* Upload weights */}
      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">Upload weights</h2>
      <form onSubmit={upload} className="mt-3 rounded-xl border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-muted">
            As of{" "}
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
            />
          </label>
          <span className="text-xs text-muted">One per line: <code className="font-mono">TICKER, weight</code> (e.g. AAPL, 0.1)</span>
        </div>
        <textarea
          value={csv}
          onChange={(e) => setCsv(e.target.value)}
          rows={5}
          placeholder={"AAPL, 0.25\nNVDA, 0.30\nMSFT, 0.20"}
          className="mt-2 w-full rounded-md border border-border bg-bg px-3 py-2 font-mono text-sm text-fg outline-none focus:border-fg/40"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="submit"
            className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20"
          >
            Upload
          </button>
          {msg && <span className="text-xs text-muted">{msg}</span>}
        </div>
      </form>

      <p className="mt-6 text-xs text-muted">
        Weights stored in QRP's own schema; returns weight sym's EOD returns. Swap in a live
        quote source later for intraday PnL — same engine.
      </p>
    </div>
  );
}
