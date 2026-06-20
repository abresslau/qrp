"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { PortfolioHeatmap, type Composition } from "@/components/portfolio-heatmap";
import { PortfolioMovers } from "@/components/portfolio-movers";
import { PortfolioPivot } from "@/components/portfolio-pivot";
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

// LIVE Daily/MTD/YTD P&L = Σ weight·return (FX-hedged — base currency, no FX translation, no
// coverage-normalisation). This is the SAME plain weight×return roll-up the grid's P&L columns sum to,
// so the panel's Daily/MTD/YTD P&L match the grid's grand totals exactly. Daily uses the live return;
// MTD/YTD use the (live-re-based) trailing windows on each holding.
function weightedPnl(comp: Composition | null, ret: (h: Composition["holdings"][number]) => number | null): number | null {
  if (!comp?.holdings?.length) return null;
  let num = 0;
  let any = false;
  for (const h of comp.holdings) {
    const r = ret(h);
    if (r != null) {
      num += h.weight * r;
      any = true;
    }
  }
  return any ? num : null;
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
    <div className="w-full space-y-4">
      {/* Header — title + nav buttons on the same row */}
      <div className="flex flex-wrap items-start justify-between gap-2">
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
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href={`/portfolios/${id}`}
            className="rounded-md border border-border px-2.5 py-1 text-sm text-muted hover:bg-fg/5 hover:text-fg"
          >
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
      </div>

      <PortfolioRiskPnl
        portfolio={p}
        dailyReturn={weightedPnl(comp, (h) => h.live_return)}
        mtdReturn={weightedPnl(comp, (h) => h.window_returns?.["MTD"] ?? null)}
        ytdReturn={weightedPnl(comp, (h) => h.window_returns?.["YTD"] ?? null)}
      />

      {compErr && (
        <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          Couldn&apos;t load live composition: {compErr}
        </div>
      )}
      {comp ? (
        <>
          {/* Sector donut + top movers — two separate cards, side by side */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-surface p-4">
              <PortfolioPizza data={comp} />
            </div>
            <div className="rounded-xl border border-border bg-surface p-4">
              <PortfolioMovers pid={String(id)} composition={comp} />
            </div>
          </div>
          <PortfolioHeatmap data={comp} />
          {/* Pivot grid — book grouped by sector with explorer columns + return + P&L */}
          <PortfolioPivot data={comp} />
        </>
      ) : !compErr ? (
        <p className="text-sm text-muted">Loading live composition…</p>
      ) : null}
    </div>
  );
}
