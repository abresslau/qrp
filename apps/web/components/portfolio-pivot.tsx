"use client";

import { type Composition, type CompositionHolding } from "@/components/portfolio-heatmap";
import { fmtCompact, fmtPrice } from "@/lib/format";

// A pivot-style grid: the book grouped by sector, each stock carrying the Explorer columns
// (country / exchange / ccy / price / volume / market cap / status) PLUS its weight, live return,
// and P&L contribution (Σ w·r ÷ Σ|w| covered — the column totals to the portfolio Daily P&L).

function pct(r: number | null): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function wpct(w: number | null): string {
  return w == null ? "—" : `${w >= 0 ? "" : "−"}${(Math.abs(w) * 100).toFixed(1)}%`;
}
function retClass(r: number | null): string {
  if (r == null) return "text-muted";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

export function PortfolioPivot({ data }: { data: Composition | null }) {
  if (!data?.holdings?.length) {
    return <p className="text-sm text-muted">No holdings yet — upload a weight vector to see the breakdown.</p>;
  }

  const priced = data.holdings.filter((h) => h.live_return != null);
  const covered = priced.reduce((s, h) => s + Math.abs(h.weight), 0);
  const contrib = (h: CompositionHolding): number | null =>
    h.live_return != null && covered > 0 ? (h.weight * h.live_return) / covered : null;

  // Group by sector, sectors ordered by gross weight desc, holdings within by |weight| desc.
  const bySector: Record<string, CompositionHolding[]> = {};
  for (const h of data.holdings) (bySector[h.sector] ||= []).push(h);
  const sectors = Object.entries(bySector)
    .map(([sector, hs]) => {
      hs.sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
      const wt = hs.reduce((s, h) => s + Math.abs(h.weight), 0);
      const pnl = hs.reduce((s, h) => s + (contrib(h) ?? 0), 0);
      return { sector, hs, wt, pnl };
    })
    .sort((a, b) => b.wt - a.wt);

  const totalPnl = sectors.reduce((s, x) => s + x.pnl, 0);
  const COLS = 11;

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="w-full min-w-[56rem] text-xs">
        <thead className="border-b border-border bg-fg/5 text-left text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">Ticker</th>
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Country</th>
            <th className="px-3 py-2 font-medium">Exch</th>
            <th className="px-3 py-2 font-medium">Ccy</th>
            <th className="px-3 py-2 text-right font-medium">Wt</th>
            <th className="px-3 py-2 text-right font-medium">Price</th>
            <th className="px-3 py-2 text-right font-medium">Mkt cap</th>
            <th className="px-3 py-2 text-right font-medium">Volume</th>
            <th className="px-3 py-2 text-right font-medium">Return</th>
            <th className="px-3 py-2 text-right font-medium">P&amp;L</th>
          </tr>
        </thead>
        <tbody>
          {sectors.map(({ sector, hs, wt, pnl }) => (
            <SectorGroup key={sector} sector={sector} hs={hs} wt={wt} pnl={pnl} gross={data.total_weight} contrib={contrib} cols={COLS} />
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border bg-fg/5 font-semibold">
            <td className="px-3 py-2" colSpan={5}>
              Total · {data.n_holdings} holdings
            </td>
            <td className="px-3 py-2 text-right tabular-nums">{wpct(data.total_weight)}</td>
            <td className="px-3 py-2" colSpan={3} />
            <td className="px-3 py-2" />
            <td className={`px-3 py-2 text-right tabular-nums ${retClass(totalPnl)}`}>{pct(totalPnl)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function SectorGroup({
  sector,
  hs,
  wt,
  pnl,
  gross,
  contrib,
  cols,
}: {
  sector: string;
  hs: CompositionHolding[];
  wt: number;
  pnl: number;
  gross: number;
  contrib: (h: CompositionHolding) => number | null;
  cols: number;
}) {
  return (
    <>
      {/* sector subtotal row (the pivot grouping) */}
      <tr className="border-y border-border bg-bg/40 text-[11px] uppercase tracking-wide text-muted">
        <td className="px-3 py-1.5 font-semibold text-fg" colSpan={cols - 2}>
          {sector} <span className="font-normal text-muted">· {hs.length}</span>
        </td>
        <td className="px-3 py-1.5 text-right font-semibold tabular-nums text-fg">
          {gross > 0 ? `${((wt / gross) * 100).toFixed(1)}%` : "—"}
        </td>
        <td className={`px-3 py-1.5 text-right font-semibold tabular-nums ${retClass(pnl)}`}>{pct(pnl)}</td>
      </tr>
      {hs.map((h) => (
        <tr key={h.figi} className="border-b border-border/50 hover:bg-fg/5">
          <td className="px-3 py-1.5 font-medium text-fg">{h.ticker ?? h.figi}</td>
          <td className="max-w-[16rem] truncate px-3 py-1.5 text-muted" title={h.name ?? ""}>{h.name ?? "—"}</td>
          <td className="px-3 py-1.5 text-muted">{h.country ?? "—"}</td>
          <td className="px-3 py-1.5 text-muted">{h.mic ?? "—"}</td>
          <td className="px-3 py-1.5 text-muted">{h.currency ?? "—"}</td>
          <td className="px-3 py-1.5 text-right tabular-nums text-fg">{wpct(h.weight)}</td>
          <td className="px-3 py-1.5 text-right tabular-nums text-fg">{fmtPrice(h.price)}</td>
          <td className="px-3 py-1.5 text-right tabular-nums text-muted">{h.market_cap_usd == null ? "—" : `$${fmtCompact(h.market_cap_usd)}`}</td>
          <td className="px-3 py-1.5 text-right tabular-nums text-muted">{fmtCompact(h.volume)}</td>
          <td className={`px-3 py-1.5 text-right tabular-nums ${retClass(h.live_return)}`}>{pct(h.live_return)}</td>
          <td className={`px-3 py-1.5 text-right tabular-nums ${retClass(contrib(h))}`}>{pct(contrib(h))}</td>
        </tr>
      ))}
    </>
  );
}
