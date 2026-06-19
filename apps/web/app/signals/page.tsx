"use client";

import { useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type FactorSummary = Schemas["FactorSummary"];
type FactorRanking = Schemas["FactorRanking"];

const UNIVERSES = ["sp500", "ibov", "ibx"];

function fmtRaw(key: string, v: number): string {
  if (key === "size") {
    const b = v / 1e9;
    return b >= 1000 ? `$${(b / 1000).toFixed(2)}T` : `$${b.toFixed(1)}B`;
  }
  if (key === "wiki_attention") return `${v.toFixed(2)}×`; // 7d/30d attention ratio
  if (key === "fiscal_sens") return v.toFixed(2); // a beta, not a fraction
  return `${(v * 100).toFixed(1)}%`; // momentum, vol are fractions
}

const INPUT_TONE: Record<string, string> = {
  sym: "border-sky-500/40 text-sky-700 dark:text-sky-300",
  macro: "border-amber-500/40 text-amber-700 dark:text-amber-300",
  altdata: "border-emerald-500/40 text-emerald-700 dark:text-emerald-300",
};

function InputChip({ refStr }: { refStr: string }) {
  const moduleKey = refStr.split(":")[0];
  const tone = INPUT_TONE[moduleKey] ?? "border-border text-muted";
  return (
    <span className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${tone}`}>
      {refStr}
    </span>
  );
}

export default function SignalPage() {
  const [factors, setFactors] = useState<FactorSummary[]>([]);
  const [factor, setFactor] = useState("mom_12_1");
  const [universe, setUniverse] = useState("sp500");
  const [bottom, setBottom] = useState(false);
  const [data, setData] = useState<FactorRanking | null>(null);

  useEffect(() => {
    fetch("/api/signals/factors", { cache: "no-store" })
      .then((r) => r.json())
      .then(setFactors)
      .catch(() => setFactors([]));
  }, []);

  useEffect(() => {
    fetch(
      `/api/signals/factors/${factor}?universe=${universe}&limit=25&bottom=${bottom}`,
      { cache: "no-store" },
    )
      // a 404 (no scores for this factor/universe — routine for sparse factors) must
      // render the empty state, never store the error envelope as a ranking
      .then((r) => (r.ok ? r.json() : null))
      .then((d: FactorRanking | null) => setData(d))
      .catch(() => setData(null));
  }, [factor, universe, bottom]);

  const meta = factors.find((f) => f.factor_key === factor);

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">signal</h1>
      <p className="mt-1 text-sm text-muted">
        Derived cross-sectional factors with inputs across modules — sym returns, macro series,
        altdata attention — each read from its own database (read-only) and stored in QRP&apos;s
        own schema. Every factor names its inputs and method (FR-21 traceability). Ranked within
        a universe as-of the latest returns date; coverage gaps are simply absent (never
        fabricated).
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select
          value={factor}
          onChange={(e) => setFactor(e.target.value)}
          className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
        >
          {factors.map((f) => (
            <option key={f.factor_key} value={f.factor_key}>
              {f.name}
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
          onClick={() => setBottom((b) => !b)}
          className="rounded-md border border-border bg-fg/10 px-3 py-1 text-sm font-medium text-fg hover:bg-fg/20"
        >
          {bottom ? "Showing bottom" : "Showing top"}
        </button>
      </div>

      {meta && (
        <div className="mt-2">
          <p className="text-xs text-muted">
            {meta.description} · favourable end:{" "}
            <span className="font-medium">{meta.direction === "high" ? "higher" : "lower"}</span>{" "}
            raw
            {data?.as_of_date ? ` · as of ${data.as_of_date}` : ""}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] uppercase tracking-wide text-muted">inputs</span>
            {meta.inputs.map((ref) => (
              <InputChip key={ref} refStr={ref} />
            ))}
          </div>
          {meta.method && (
            <p className="mt-1.5 text-xs text-muted">
              <span className="uppercase tracking-wide">method</span> · {meta.method}
            </p>
          )}
        </div>
      )}

      <div className="mt-3 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Rank</th>
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 text-right font-medium">Value</th>
              <th className="px-3 py-2 text-right font-medium">z-score</th>
              <th className="px-3 py-2 text-right font-medium">pctile</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {(data?.constituents ?? []).map((c) => (
              <tr key={`${c.rank}-${c.ticker}`} className="hover:bg-fg/5">
                <td className="px-3 py-2 tabular-nums text-muted">{c.rank}</td>
                <td className="px-3 py-2 font-medium text-fg">{c.ticker}</td>
                <td className="px-3 py-2 text-muted">{c.name ?? "—"}</td>
                <td className="px-3 py-2 text-right tabular-nums text-fg">
                  {fmtRaw(factor, c.raw)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">
                  {c.zscore == null ? "—" : c.zscore.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">
                  {c.pctile == null ? "—" : (c.pctile * 100).toFixed(0)}
                </td>
              </tr>
            ))}
            {(!data || data.constituents.length === 0) && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-muted">
                  No scores for this factor / universe.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
