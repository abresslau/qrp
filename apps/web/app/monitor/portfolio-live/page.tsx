"use client";

// Portfolio live (Monitor) — a launcher for the per-portfolio live cockpit. The cockpit itself is
// inherently per-book (/portfolios/[id]/live), so this monitor screen lists the portfolios and opens
// each one's live view. Honest empty/error states; no fabricated data.

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type P = Schemas["PortfolioSummary"];

export default function PortfolioLiveMonitor() {
  const [list, setList] = useState<P[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/portfolios", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`portfolios ${r.status}`))))
      .then((d: P[]) => alive && setList(d))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="w-full">
      <header className="mb-4">
        <h1 className="text-lg font-semibold text-fg">Portfolio live</h1>
        <p className="mt-1 text-sm text-muted">
          Open a book&apos;s live cockpit — risk &amp; P&amp;L, sector mix, top movers, intraday grid.
        </p>
      </header>

      {error ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-rose-500">
          Could not load portfolios: {error}
        </p>
      ) : list == null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : list.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
          No portfolios yet. Create one in the <Link href="/portfolios" className="underline">Portfolios</Link> area.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-sm [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
            <thead className="text-[10px] uppercase tracking-wide text-muted">
              <tr className="border-b border-border">
                <th className="px-3 py-1.5 text-left font-medium">Portfolio</th>
                <th className="px-3 py-1.5 text-left font-medium">Client</th>
                <th className="px-3 py-1.5 text-right font-medium">Ccy</th>
                <th className="px-3 py-1.5 text-right font-medium">Holdings</th>
                <th className="px-3 py-1.5 text-right font-medium">As of</th>
                <th className="px-3 py-1.5 text-right font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.portfolio_id} className="border-b border-border/40 last:border-0 hover:bg-fg/5">
                  <td className="px-3 py-1.5 font-medium text-fg">{p.name}</td>
                  <td className="px-3 py-1.5 text-muted">{p.client}</td>
                  <td className="px-3 py-1.5 text-right text-muted">{p.base_currency}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted">{p.n_holdings}</td>
                  <td className="px-3 py-1.5 text-right text-xs text-muted">{p.latest_as_of_date ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right">
                    <Link
                      href={`/portfolios/${p.portfolio_id}/live`}
                      className="rounded-md border border-border px-2 py-0.5 text-xs text-fg hover:bg-fg/5"
                    >
                      Live ▸
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
