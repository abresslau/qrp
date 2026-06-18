"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fmtCompact, fmtPrice } from "@/lib/format";

type Row = {
  figi: string;
  ticker: string;
  name: string | null;
  mic: string | null;
  currency: string | null;
  status: string | null;
  price: number | null;
  session_date: string | null;
  volume: number | null;
  market_cap_usd: number | null;
  country: string | null;
  country_iso: string | null;
  sector: string | null;
};
type Resp = { total: number; limit: number; offset: number; rows: Row[] };
type Uni = { universe_id: string; name: string | null; members_resolved: number };

const LIMIT = 50;

export default function ExplorerPage() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(true);
  const [universe, setUniverse] = useState("");
  const [universes, setUniverses] = useState<Uni[]>([]);
  const [gap, setGap] = useState(""); // a layer (prices/returns/fundamentals) to show only the gap names

  // universe options for the dropdown + the initial filter from the ?u= deep-link (the
  // Universes landing links here with it). Both are set inside the fetch's async callback —
  // not synchronously in the effect body (react-hooks/set-state-in-effect) — and reading
  // window there avoids useSearchParams (which would force a Suspense boundary).
  useEffect(() => {
    fetch("/api/sym/universes", { cache: "no-store" })
      .then((r) => r.json())
      .then((list: Uni[]) => {
        setUniverses(list);
        const params = new URLSearchParams(window.location.search);
        const u = params.get("u");
        if (u) setUniverse(u);
        const g = params.get("gap");
        if (g) setGap(g);
      })
      .catch(() => setUniverses([]));
  }, []);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(
      () => {
        // setLoading lives in the (deferred) timer callback, not the synchronous effect body
        // (react-hooks/set-state-in-effect); loading shows as the debounced fetch starts.
        setLoading(true);
        const url = `/api/sym/securities?limit=${LIMIT}&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ""}${universe ? `&universe=${encodeURIComponent(universe)}` : ""}${gap && universe ? `&gap=${encodeURIComponent(gap)}` : ""}`;
        fetch(url, { cache: "no-store" })
          .then((r) => r.json())
          .then((d: Resp) => {
            if (alive) {
              setData(d);
              setLoading(false);
            }
          })
          .catch(() => alive && setLoading(false));
      },
      q ? 250 : 0,
    );
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q, offset, universe, gap]);

  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + LIMIT, total);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold tracking-tight text-fg">Securities</h1>
        <div className="flex items-center gap-2">
          <select
            value={universe}
            onChange={(e) => {
              setLoading(true);
              setUniverse(e.target.value);
              setGap(""); // switching universe clears the layer-gap filter (it was universe-specific)
              setOffset(0);
            }}
            className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-fg outline-none focus:border-fg/40"
          >
            <option value="">All universes</option>
            {universes.map((u) => (
              <option key={u.universe_id} value={u.universe_id}>
                {u.name ?? u.universe_id} ({u.members_resolved.toLocaleString()})
              </option>
            ))}
          </select>
          <input
            value={q}
            onChange={(e) => {
              // Immediate loading feedback on type (an event handler — lint-safe); the debounced
              // effect re-affirms it for the offset path. Restores the pre-lint-fix UX.
              setLoading(true);
              setQ(e.target.value);
              setOffset(0);
            }}
            placeholder="Search ticker, name, or FIGI…"
            className="w-72 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg outline-none focus:border-fg/40"
          />
        </div>
      </div>

      {gap && universe && (
        <div className="mb-2 flex items-center gap-2 text-xs">
          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 font-medium text-amber-700 ring-1 ring-amber-600/20 dark:text-amber-400 dark:ring-amber-500/30">
            Missing data
          </span>
          <button
            onClick={() => {
              setLoading(true);
              setGap("");
              setOffset(0);
            }}
            className="text-muted underline hover:text-fg"
          >
            clear
          </button>
        </div>
      )}

      <div className="mb-2 text-xs text-muted">
        {loading ? "Loading…" : `${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}`}
      </div>

      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Ticker</th>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Sector</th>
              <th className="px-4 py-2 font-medium">Country</th>
              <th className="px-4 py-2 font-medium">Exchange</th>
              <th className="px-4 py-2 font-medium">Ccy</th>
              <th className="px-4 py-2 text-right font-medium">Price</th>
              <th className="px-4 py-2 text-right font-medium">Volume</th>
              <th className="px-4 py-2 text-right font-medium">Mkt cap</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {(data?.rows ?? []).map((r) => (
              <tr key={r.figi} className="hover:bg-fg/5">
                <td className="px-4 py-2 font-medium">
                  <Link href={`/sym/securities/${r.figi}`} className="hover:underline">
                    {r.ticker}
                  </Link>
                </td>
                <td className="px-4 py-2 text-muted">{r.name ?? "—"}</td>
                <td className="px-4 py-2 text-muted">{r.sector ?? "—"}</td>
                <td className="px-4 py-2 text-muted">{r.country_iso ?? "—"}</td>
                <td className="px-4 py-2 tabular-nums text-muted">{r.mic ?? "—"}</td>
                <td className="px-4 py-2 text-muted">{r.currency ?? "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums text-fg" title={r.session_date ?? undefined}>
                  {fmtPrice(r.price)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">{fmtCompact(r.volume)}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
                  {r.market_cap_usd != null ? `$${fmtCompact(r.market_cap_usd)}` : "—"}
                </td>
                <td className="px-4 py-2 text-muted">{r.status ?? "—"}</td>
              </tr>
            ))}
            {!loading && data?.rows.length === 0 && (
              <tr>
                <td colSpan={10} className="px-4 py-6 text-center text-muted">
                  No matches.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-end gap-2 text-sm">
        <button
          onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          disabled={offset === 0}
          className="rounded-md border border-border px-3 py-1 text-fg disabled:opacity-40"
        >
          ← Prev
        </button>
        <button
          onClick={() => setOffset(offset + LIMIT)}
          disabled={to >= total}
          className="rounded-md border border-border px-3 py-1 text-fg disabled:opacity-40"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
