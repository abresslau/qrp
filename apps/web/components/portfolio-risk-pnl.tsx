"use client";

import { useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type Portfolio = Schemas["PortfolioDetail"];
type Pnl = Schemas["PnlSummary"];

function pct(r: number | null | undefined): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function expPct(w: number | null | undefined): string {
  return w == null ? "—" : `${(w * 100).toFixed(1)}%`;
}
function signedExpPct(w: number | null | undefined): string {
  return w == null ? "—" : `${w >= 0 ? "+" : ""}${(w * 100).toFixed(1)}%`;
}
function tone(r: number | null | undefined): string {
  if (r == null) return "text-fg";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

// One compact label/value stat — the whole panel is a single wrapping row of these.
function Stat({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${cls ?? "text-fg"}`}>{value}</span>
    </div>
  );
}

export function PortfolioRiskPnl({
  pid,
  portfolio,
  dailyReturn,
}: {
  pid: string;
  portfolio: Portfolio | null;
  // LIVE portfolio daily return (Σ w·r ÷ Σ|w| covered) from the SAME composition that drives the
  // heat map + donut, so the top Daily P&L is their exact weighted roll-up. MTD/YTD come from the EOD series.
  dailyReturn: number | null;
}) {
  const [pnl, setPnl] = useState<Pnl | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    fetch(`/api/analytics/portfolios/${pid}/pnl`, { cache: "no-store", signal: ac.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`pnl ${r.status}`))))
      .then((d: Pnl) => {
        if (!ac.signal.aborted) setPnl(d);
      })
      .catch(() => {
        if (!ac.signal.aborted) setPnl(null);
      });
    return () => ac.abort();
  }, [pid]);

  const long = portfolio?.long_exposure ?? null;
  const short = portfolio?.short_exposure ?? null;
  const ls = long != null && short != null && short > 0 ? long / short : null;

  return (
    <div>
      <h2 className="text-sm font-medium uppercase tracking-wide text-muted">Risk &amp; P&amp;L analytics</h2>
      <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-border bg-surface px-4 py-3">
        <Stat label="Daily P&L" value={pct(dailyReturn)} cls={tone(dailyReturn)} />
        <Stat label="MTD P&L" value={pct(pnl?.mtd_return)} cls={tone(pnl?.mtd_return)} />
        <Stat label="YTD P&L" value={pct(pnl?.ytd_return)} cls={tone(pnl?.ytd_return)} />
        <div className="h-8 w-px self-center bg-border" aria-hidden />
        <Stat label="Long" value={expPct(long)} cls="text-emerald-600 dark:text-emerald-400" />
        <Stat label="Short" value={expPct(short)} cls="text-rose-600 dark:text-rose-400" />
        <Stat label="Net" value={signedExpPct(portfolio?.net_exposure)} cls={tone(portfolio?.net_exposure)} />
        <Stat label="Gross" value={expPct(portfolio?.gross_exposure)} />
        <Stat label="L/S" value={ls == null ? "—" : `${ls.toFixed(2)}×`} />
      </div>
    </div>
  );
}
