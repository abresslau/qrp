import Link from "next/link";
import { NewsPanel } from "@/components/news-panel";
import { PriceVolumeChart } from "@/components/price-volume-chart";
import { QualifiedTicker } from "@/components/qualified-ticker";
import { apiGet } from "@/lib/api";
import { fmtCompact } from "@/lib/format";

type Ret = { code: string; label: string; pr: number | null; tr: number | null; as_of_date: string | null };
type ClassBySource = {
  source: string;
  sector: string | null;
  industry: string | null;
  sub_industry: string | null;
  effective: boolean;
};
type Detail = {
  figi: string;
  ticker: string;
  name: string | null;
  mic: string | null;
  currency: string | null;
  status: string | null;
  delist_date: string | null;
  country: string | null;
  country_iso: string | null;
  exch_code: string | null;
  bbg_exchange_code: string | null;
  sector: string | null;
  industry: string | null;
  sub_industry: string | null;
  source: string | null;
  classifications: ClassBySource[];
  price: { close: number | null; volume: number | null; session_date: string | null };
  fundamentals: {
    market_cap_lcy: number | null;
    market_cap_usd: number | null;
    shares_outstanding: number | null;
    currency: string | null;
    as_of_date: string | null;
  } | null;
  returns: Ret[];
};

function pct(r: number | null): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function retClass(r: number | null): string {
  if (r == null) return "text-muted";
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}
const fmtCap = fmtCompact;

export default async function SecurityPage({ params }: { params: Promise<{ figi: string }> }) {
  const { figi } = await params;
  let d: Detail | null = null;
  try {
    d = await apiGet<Detail>(`/api/sym/securities/${figi}`);
  } catch {
    d = null;
  }

  if (!d) {
    return (
      <div>
        <Link href="/sym/explorer" className="text-sm text-muted hover:text-fg">
          ← Explorer
        </Link>
        <p className="mt-4 text-sm text-rose-600 dark:text-rose-400">
          Security not found (or API unreachable): {figi}
        </p>
      </div>
    );
  }

  const f = d.fundamentals;
  return (
    <div className="w-full">
      <Link href="/sym/explorer" className="text-sm text-muted hover:text-fg">
        ← Explorer
      </Link>

      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">
            <QualifiedTicker codes={d} /> <span className="text-lg font-normal text-muted">· {d.name ?? "—"}</span>
          </h1>
          <p className="mt-1 text-sm text-muted">
            {[d.sector, d.industry, d.sub_industry].filter(Boolean).join(" · ") || "Unclassified"}
            {d.source && <span className="ml-2 text-xs text-muted/70">via {d.source}</span>}
          </p>
        </div>
        <div className="text-right text-sm text-muted">
          <div className="font-mono text-xs">{d.figi}</div>
          <div>
            {d.mic ?? "—"} · {d.country ?? d.country_iso ?? "—"} · {d.currency ?? "—"} · {d.status ?? "—"}
          </div>
        </div>
      </div>

      <div className="mt-6">
        <PriceVolumeChart figi={d.figi} currency={d.currency} />
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs uppercase tracking-wide text-muted">Close ({d.currency})</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {d.price.close != null ? d.price.close.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
          </div>
          <div className="mt-1 text-xs text-muted">{d.price.session_date ?? "—"}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs uppercase tracking-wide text-muted">Volume</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">{fmtCap(d.price.volume)}</div>
          <div className="mt-1 text-xs text-muted">{d.price.session_date ?? "—"}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs uppercase tracking-wide text-muted">Market cap (USD)</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {f ? `$${fmtCap(f.market_cap_usd)}` : "—"}
          </div>
          <div className="mt-1 text-xs text-muted">{f?.as_of_date ?? "—"}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs uppercase tracking-wide text-muted">Market cap ({f?.currency ?? "LCY"})</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {f ? fmtCap(f.market_cap_lcy) : "—"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs uppercase tracking-wide text-muted">Shares out.</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {f?.shares_outstanding != null ? fmtCap(f.shares_outstanding) : "—"}
          </div>
        </div>
      </div>

      {d.classifications.length > 0 && (
        <>
          <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">
            Classification by source
          </h2>
          <div className="mt-3 overflow-hidden rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface text-left text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">Sector</th>
                  <th className="px-4 py-2 font-medium">Industry</th>
                  <th className="px-4 py-2 font-medium">Sub-industry</th>
                  <th className="px-4 py-2 font-medium">Effective</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {d.classifications.map((c) => (
                  <tr key={c.source} className="hover:bg-fg/5">
                    <td className="px-4 py-2 font-mono text-xs text-fg">{c.source}</td>
                    <td className="px-4 py-2 text-muted">{c.sector ?? "—"}</td>
                    <td className="px-4 py-2 text-muted">{c.industry ?? "—"}</td>
                    <td className="px-4 py-2 text-muted">{c.sub_industry ?? "—"}</td>
                    <td className="px-4 py-2 text-muted">
                      {c.effective ? <span className="text-emerald-600 dark:text-emerald-400">✓ effective</span> : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">As recorded per source — the effective row wins by precedence.</p>
        </>
      )}

      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">
        Returns across windows
      </h2>
      <div className="mt-3 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Window</th>
              <th className="px-4 py-2 text-right font-medium">Price return</th>
              <th className="px-4 py-2 text-right font-medium">Total return</th>
              <th className="px-4 py-2 text-right font-medium">As of</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {d.returns.map((r) => (
              <tr key={r.code} className="hover:bg-fg/5">
                <td className="px-4 py-2 text-fg">
                  {r.label} <span className="text-xs text-muted">({r.code})</span>
                </td>
                <td className={`px-4 py-2 text-right tabular-nums ${retClass(r.pr)}`}>{pct(r.pr)}</td>
                <td className={`px-4 py-2 text-right tabular-nums ${retClass(r.tr)}`}>{pct(r.tr)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">{r.as_of_date ?? "—"}</td>
              </tr>
            ))}
            {d.returns.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  No returns computed for this security.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <NewsPanel figi={d.figi} />

      <p className="mt-6 text-xs text-muted">All figures are live reads of sym — every number ties to the warehouse.</p>
    </div>
  );
}
