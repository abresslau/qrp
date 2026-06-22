"use client";

import type { Schemas } from "@/lib/api";

type Portfolio = Schemas["PortfolioDetail"];

function pct(r: number | null | undefined): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
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

// One compact label/value stat. `sub` is an optional secondary line (the P&L amount under the return %).
function Stat({ label, value, cls, sub }: { label: string; value: string; cls?: string; sub?: string | null }) {
  return (
    <div className="flex flex-col whitespace-nowrap">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${cls ?? "text-fg"}`}>{value}</span>
      {sub ? <span className="text-[11px] tabular-nums text-muted">{sub}</span> : null}
    </div>
  );
}

// Compact, chrome-less Daily/MTD/YTD P&L strip — lives in the live-page header beside the title (no
// card border, no heading). LIVE Daily/MTD/YTD P&L = Σ weight·return from the SAME composition that
// drives the grid, heat map and donut (FX-hedged, plain weight×return), so these match the grid's
// grand totals. Daily uses the live return; MTD/YTD use the (live-re-based) trailing windows. The
// risk/exposure stats (Long/Short/Net/Gross/L/S) were intentionally removed from the live cockpit.
export function PortfolioPnlStrip({
  portfolio,
  dailyReturn,
  mtdReturn,
  ytdReturn,
}: {
  portfolio: Portfolio | null;
  dailyReturn: number | null;
  mtdReturn: number | null;
  ytdReturn: number | null;
}) {
  // P&L amounts (base currency) shown under the % returns when the portfolio states a notional —
  // each = its return × notional, consistent with the % above. No notional → no amount (null).
  const ccy = portfolio?.base_currency ?? null;
  const notional = portfolio?.notional ?? null;
  const amt = (r: number | null): number | null => (r != null && notional != null ? r * notional : null);

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1" data-testid="pnl-strip">
      <Stat label="Daily P&L" value={pct(dailyReturn)} cls={tone(dailyReturn)} sub={money(amt(dailyReturn), ccy)} />
      <Stat label="MTD P&L" value={pct(mtdReturn)} cls={tone(mtdReturn)} sub={money(amt(mtdReturn), ccy)} />
      <Stat label="YTD P&L" value={pct(ytdReturn)} cls={tone(ytdReturn)} sub={money(amt(ytdReturn), ccy)} />
    </div>
  );
}
