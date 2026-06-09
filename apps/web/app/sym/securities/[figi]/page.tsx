import Link from "next/link";
import { apiGet } from "@/lib/api";

type Ret = { code: string; label: string; pr: number | null; tr: number | null; as_of_date: string | null };
type Detail = {
  figi: string;
  ticker: string;
  name: string | null;
  mic: string | null;
  currency: string | null;
  status: string | null;
  delist_date: string | null;
  sector: string | null;
  industry: string | null;
  sub_industry: string | null;
  price: { close: number | null; session_date: string | null };
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
function fmtCap(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return v.toFixed(0);
}

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
    <div className="mx-auto max-w-4xl">
      <Link href="/sym/explorer" className="text-sm text-muted hover:text-fg">
        ← Explorer
      </Link>

      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">
            {d.ticker} <span className="text-lg font-normal text-muted">· {d.name ?? "—"}</span>
          </h1>
          <p className="mt-1 text-sm text-muted">
            {[d.sector, d.industry, d.sub_industry].filter(Boolean).join(" · ") || "Unclassified"}
          </p>
        </div>
        <div className="text-right text-sm text-muted">
          <div className="font-mono text-xs">{d.figi}</div>
          <div>
            {d.mic ?? "—"} · {d.currency ?? "—"} · {d.status ?? "—"}
          </div>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs uppercase tracking-wide text-muted">Close ({d.currency})</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">
            {d.price.close != null ? d.price.close.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
          </div>
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

      <p className="mt-6 text-xs text-muted">All figures are live reads of sym — every number ties to the warehouse.</p>
    </div>
  );
}
