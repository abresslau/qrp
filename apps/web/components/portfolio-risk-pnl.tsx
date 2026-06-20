"use client";

import type { Schemas } from "@/lib/api";

type Portfolio = Schemas["PortfolioDetail"];

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

// Signed, compact currency for the P&L amount sub-line (e.g. "+USD 16.4K", "−USD 39.1M"). Returns
// null when there's no amount (no notional set) so the sub-line is simply omitted — the % return
// above still stands on its own.
function money(v: number | null | undefined, ccy: string | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  const sign = v >= 0 ? "+" : "−";
  const a = Math.abs(v);
  const mag =
    a >= 1e9 ? `${(a / 1e9).toFixed(2)}B`
    : a >= 1e6 ? `${(a / 1e6).toFixed(2)}M`
    : a >= 1e3 ? `${(a / 1e3).toFixed(1)}K`
    : a.toFixed(0);
  return `${sign}${ccy ? `${ccy} ` : ""}${mag}`;
}

// One compact label/value stat — the whole panel is a single wrapping row of these. `sub` is an
// optional secondary line (used for the P&L amount under the return %).
function Stat({ label, value, cls, sub }: { label: string; value: string; cls?: string; sub?: string | null }) {
  return (
    <div className="flex flex-col whitespace-nowrap">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${cls ?? "text-fg"}`}>{value}</span>
      {sub ? <span className="text-[11px] tabular-nums text-muted">{sub}</span> : null}
    </div>
  );
}

export function PortfolioRiskPnl({
  portfolio,
  dailyReturn,
  mtdReturn,
  ytdReturn,
}: {
  portfolio: Portfolio | null;
  // LIVE Daily/MTD/YTD P&L = Σ weight·return from the SAME composition that drives the grid, heat map
  // and donut (FX-hedged, plain weight×return), so these panel figures match the grid's grand totals.
  dailyReturn: number | null;
  mtdReturn: number | null;
  ytdReturn: number | null;
}) {
  const long = portfolio?.long_exposure ?? null;
  const short = portfolio?.short_exposure ?? null;
  const ls = long != null && short != null && short > 0 ? long / short : null;

  // P&L amounts (base currency) shown under the % returns when the portfolio states a notional —
  // each = its return × notional, consistent with the % above. No notional → no amount (null).
  const ccy = portfolio?.base_currency ?? null;
  const notional = portfolio?.notional ?? null;
  const amt = (r: number | null): number | null => (r != null && notional != null ? r * notional : null);

  return (
    <div>
      <h2 className="text-sm font-medium uppercase tracking-wide text-muted">Risk &amp; P&amp;L analytics</h2>
      <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-border bg-surface px-4 py-3">
        <Stat label="Daily P&L" value={pct(dailyReturn)} cls={tone(dailyReturn)} sub={money(amt(dailyReturn), ccy)} />
        <Stat label="MTD P&L" value={pct(mtdReturn)} cls={tone(mtdReturn)} sub={money(amt(mtdReturn), ccy)} />
        <Stat label="YTD P&L" value={pct(ytdReturn)} cls={tone(ytdReturn)} sub={money(amt(ytdReturn), ccy)} />
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
