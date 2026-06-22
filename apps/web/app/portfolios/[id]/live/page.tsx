"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { PortfolioHeatmap, type Composition } from "@/components/portfolio-heatmap";
import { PortfolioMovers } from "@/components/portfolio-movers";
import { PortfolioPivot } from "@/components/portfolio-pivot";
import { PortfolioDonut } from "@/components/portfolio-donut";
import { PortfolioPnlStrip } from "@/components/portfolio-pnl-strip";
import { useOnline } from "@/lib/connection";
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
  // Live composition (heat map + donut) — ONE fetch feeds both visuals. Newest-wins via an
  // AbortController (a slow/superseded request can't overwrite the current view); `nonce` bumps a
  // manual refresh. Not persisted — fetched at view time, like the analytics-panel Live PnL.
  const [comp, setComp] = useState<Composition | null>(null);
  const [compLoading, setCompLoading] = useState(true);
  const [compErr, setCompErr] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [autoSec, setAutoSec] = useState(0); // auto-refresh interval in seconds; 0 = off
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null); // local clock of the last live pull
  const online = useOnline(); // sidebar offline toggle pauses auto-refresh

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
          // Stamp the LOCAL clock each settle so an auto-refresh shows visible confirmation even when
          // the data's own `as_of` (sim-clock) doesn't move — mirrors the WEI/FX/heatmap live boards.
          setRefreshedAt(new Date().toLocaleTimeString());
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

  // Auto-refresh: while a positive interval is set AND the app is online (sidebar toggle), bump the
  // refresh nonce on a timer (re-pulls via the effect above). setState lives in the timer callback, not
  // the effect body (react-hooks/set-state-in-effect). Floored at 3s to stay polite; going offline
  // clears the timer (deps). Mirrors the WEI/FX boards + the heatmap-view LIVE refresh.
  useEffect(() => {
    if (autoSec <= 0 || !online) return;
    const tid = setInterval(() => setNonce((n) => n + 1), Math.max(3, autoSec) * 1000);
    return () => clearInterval(tid);
  }, [autoSec, online]);

  return (
    <div className="w-full space-y-3 2xl:space-y-4">
      {/* Header — title + live P&L strip (left) and nav buttons (right) on one row */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
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
                  {comp.as_of && !compLoading ? ` · as of ${new Date(comp.as_of).toLocaleTimeString()}` : ""}
                  {refreshedAt ? ` · refreshed ${refreshedAt}` : ""} · not stored
                </>
              ) : null}
            </p>
          </div>
          {/* Live P&L moved up here, beside the title (was a separate "Risk & P&L analytics" panel) */}
          <PortfolioPnlStrip
            portfolio={p}
            dailyReturn={weightedPnl(comp, (h) => h.live_return)}
            mtdReturn={weightedPnl(comp, (h) => h.window_returns?.["MTD"] ?? null)}
            ytdReturn={weightedPnl(comp, (h) => h.window_returns?.["YTD"] ?? null)}
          />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href={`/portfolios/${id}`}
            className="rounded-md border border-border px-2.5 py-1 text-sm text-muted hover:bg-fg/5 hover:text-fg"
          >
            ← Portfolio
          </Link>
          <label
            className="flex items-center gap-1 text-sm text-muted"
            title="Auto-refresh interval (seconds); blank or 0 = off. Floored at 3s. Pauses when offline."
          >
            auto
            <input
              type="number"
              min={0}
              value={autoSec || ""}
              onChange={(e) => setAutoSec(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
              placeholder="off"
              aria-label="Auto-refresh interval in seconds"
              className="w-14 rounded border border-border bg-bg px-1 py-0.5 text-fg outline-none focus:border-fg/40"
            />
            s{autoSec > 0 ? ` (every ${Math.max(3, autoSec)}s)` : ""}
          </label>
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

      {compErr && (
        <div className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          Couldn&apos;t load live composition: {compErr}
        </div>
      )}
      {comp ? (
        <>
          {/* Sector donut + top movers — two separate cards, side by side */}
          <div className="grid gap-3 2xl:gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-surface p-3 2xl:p-4">
              <PortfolioDonut data={comp} />
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 2xl:p-4">
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
