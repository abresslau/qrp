"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { PortfolioHeatmap, type Composition } from "@/components/portfolio-heatmap";
import { PortfolioMovers } from "@/components/portfolio-movers";
import { PortfolioPizza } from "@/components/portfolio-pizza";
import { PortfolioRiskPnl } from "@/components/portfolio-risk-pnl";
import type { Schemas } from "@/lib/api";

type Portfolio = Schemas["PortfolioDetail"];

// Live composition freshness badge — mirrors the analytics-panel FRESH_STYLE idiom (QH.2/QH.9).
const FRESH_STYLE: Record<string, string> = {
  live: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  delayed: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  unavailable: "border-border bg-fg/5 text-muted",
};

// The LIVE portfolio daily return: Σ w·r ÷ Σ|w| over priced holdings (coverage-normalised) — the
// exact weighted roll-up of the heat-map names and donut sectors, so the top Daily P&L matches them.
function liveDailyReturn(comp: Composition | null): number | null {
  if (!comp?.holdings?.length) return null;
  let num = 0;
  let den = 0;
  for (const h of comp.holdings) {
    if (h.live_return != null) {
      num += h.weight * h.live_return;
      den += Math.abs(h.weight);
    }
  }
  return den > 0 ? num / den : null;
}

export default function PortfolioLive() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<Portfolio | null>(null);
  // Live composition (heat map + pizza) — ONE fetch feeds both visuals. Newest-wins via an
  // AbortController (a slow/superseded request can't overwrite the current view); `nonce` bumps a
  // manual refresh. Not persisted — fetched at view time, like the analytics-panel Live PnL.
  const [comp, setComp] = useState<Composition | null>(null);
  const [compLoading, setCompLoading] = useState(true);
  const [compErr, setCompErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // Portfolio header (name + exposure); independent of the live pull.
  useEffect(() => {
    const ac = new AbortController();
    fetch(`/api/portfolios/${id}`, { cache: "no-store", signal: ac.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`portfolio ${r.status}`))))
      .then((d: Portfolio) => {
        if (!ac.signal.aborted) setP(d);
      })
      .catch(() => {
        if (!ac.signal.aborted) setP(null);
      });
    return () => ac.abort();
  }, [id]);

  useEffect(() => {
    const ac = new AbortController();
    // Fetch inside an async IIFE so the setState calls live in the async flow, not the synchronous
    // effect body (react-hooks/set-state-in-effect) — same pattern as heatmap-view.
    void (async () => {
      setCompLoading(true);
      setCompErr(null);
      try {
        const r = await fetch(`/api/analytics/portfolios/${id}/composition`, {
          cache: "no-store",
          signal: ac.signal,
        });
        if (!r.ok) {
          const body = await r.json().catch(() => null);
          throw new Error(body?.error?.message ?? body?.detail ?? `HTTP ${r.status}`);
        }
        const d: Composition = await r.json();
        if (!ac.signal.aborted) {
          setComp(d);
          setCompLoading(false);
        }
      } catch (e) {
        // An aborted request is a superseded fetch, not a failure — leave the last good view.
        if (!ac.signal.aborted) {
          setCompErr(String(e));
          setCompLoading(false);
        }
      }
    })();
    return () => ac.abort();
  }, [id, nonce]);

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex items-center justify-between gap-2">
        <Link href={`/portfolios/${id}`} className="text-sm text-muted hover:text-fg">
          ← Portfolio
        </Link>
        <button
          type="button"
          onClick={() => setNonce((n) => n + 1)}
          disabled={compLoading}
          className="rounded-md border border-border px-2.5 py-1 text-sm text-muted hover:bg-fg/5 hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className={`inline-block${compLoading ? " animate-spin" : ""}`}>↻</span> refresh
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">
            {p?.name ?? "Portfolio"} <span className="text-muted">· Live</span>
          </h1>
          <p className="mt-1 text-sm text-muted">
            {p ? `${p.client ? `${p.client} · ` : ""}${p.base_currency} · ${p.weights.length} holdings` : "Loading…"}
            {comp && comp.n_holdings > 0 ? (
              <>
                {" · "}
                <span
                  className={`rounded px-1.5 py-0.5 text-[11px] font-medium uppercase ${
                    compLoading ? FRESH_STYLE.unavailable : FRESH_STYLE[comp.freshness] ?? FRESH_STYLE.unavailable
                  }`}
                >
                  {compLoading ? "refreshing" : comp.freshness}
                </span>{" "}
                {comp.n_priced}/{comp.n_holdings} priced
                {comp.as_of && !compLoading ? ` · as of ${new Date(comp.as_of).toLocaleTimeString()}` : ""} · not
                stored
              </>
            ) : null}
          </p>
        </div>
      </div>

      {/* Risk & P&L analytics — Daily/MTD/YTD P&L + long/short/net/gross exposure + L/S ratio.
          Daily comes from the SAME composition that drives the heat map + donut (one live source). */}
      <PortfolioRiskPnl pid={String(id)} portfolio={p} dailyReturn={liveDailyReturn(comp)} />

      {/* Composition — heat map (full width), then ONE card split 50/50: sector donut + top movers. */}
      <section className="mt-8">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted">
          Composition — heat map &amp; breakdown
        </h2>
        {compErr && (
          <div className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
            Couldn&apos;t load live composition: {compErr}
          </div>
        )}
        {comp ? (
          <div className="mt-3 space-y-4">
            <div className="grid gap-6 rounded-xl border border-border bg-surface p-4 lg:grid-cols-2">
              <PortfolioPizza data={comp} />
              <div className="lg:border-l lg:border-border lg:pl-6">
                <PortfolioMovers pid={String(id)} composition={comp} />
              </div>
            </div>
            <PortfolioHeatmap data={comp} />
          </div>
        ) : !compErr ? (
          <p className="mt-3 text-sm text-muted">Loading live composition…</p>
        ) : null}
      </section>
    </div>
  );
}
