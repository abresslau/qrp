"use client";

// World Equity Indices (WEI) — a regional board of the major equity indices from index_levels:
// last level, 1-day net/% change, YTD, and an inline sparkline, colour-coded up/down. EOD (1D = last
// vs prior session); per-market staleness is marked (markets close on different calendars). A
// QRP-native take on the classic global-equity monitor — sourced entirely from our own warehouse.

import { useEffect, useMemo, useState } from "react";

type BoardRow = {
  sym_id: number;
  name: string | null;
  region: string;
  currency: string | null;
  last: number | null;
  last_date: string | null;
  prev: number | null;
  chg: number | null;
  chg_pct: number | null; // 1D
  d5: number | null;
  mtd: number | null;
  m1: number | null;
  m3: number | null;
  m6: number | null;
  ytd: number | null;
  "1y": number | null;
  "2y": number | null;
  "3y": number | null;
  "5y": number | null;
  lo_52w: number | null;
  hi_52w: number | null;
  spark: number[];
};

const REGION_ORDER = ["Americas", "EMEA", "Asia-Pacific", "Global"];

function fmtNum(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(r: number | null): string {
  if (r == null || !Number.isFinite(r)) return "—";
  return `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
const upDown = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v)
    ? "text-muted"
    : v >= 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-rose-600 dark:text-rose-400";

// Inline sparkline (recent levels), coloured by its own net direction (last vs first).
function Spark({ pts }: { pts: number[] }) {
  if (!pts || pts.length < 2) return <span className="text-muted/40">·</span>;
  const W = 56;
  const H = 14;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = max - min || 1;
  const d = pts
    .map((v, i) => `${i === 0 ? "M" : "L"}${((i / (pts.length - 1)) * W).toFixed(1)},${(H - ((v - min) / span) * H).toFixed(1)}`)
    .join(" ");
  const up = pts[pts.length - 1] >= pts[0];
  const cls = up ? "text-emerald-500" : "text-rose-500";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className={`${cls} inline-block align-middle`} aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.2} />
    </svg>
  );
}

// 52-week range bar: low — [track with a marker at the current level] — high (Bloomberg-WEI style).
// Marker colour signals proximity, matching the portfolio-live RangeBar: near-high emerald, near-low
// rose, mid amber. Tooltip carries the low/high values + where the last sits in the range.
function Range52({ lo, hi, last }: { lo: number | null; hi: number | null; last: number | null }) {
  if (lo == null || hi == null || last == null || !(hi > lo)) return <span className="text-muted/40">·</span>;
  const p = Math.max(0, Math.min(1, (last - lo) / (hi - lo)));
  const pos = p * 100;
  const tone = p >= 0.66 ? "bg-emerald-500" : p <= 0.34 ? "bg-rose-500" : "bg-amber-500";
  return (
    <span
      className="inline-flex items-center gap-1 align-middle"
      title={`52w range ${fmtNum(lo)} – ${fmtNum(hi)} · ${pos.toFixed(0)}% of range`}
    >
      <span className="text-[10px] tabular-nums text-muted/70">{fmtNum(lo)}</span>
      <span className="relative inline-block h-1.5 w-12 rounded-full bg-fg/15">
        <span
          className={`absolute top-1/2 h-2.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm ${tone}`}
          style={{ left: `${pos}%` }}
        />
      </span>
      <span className="text-[10px] tabular-nums text-muted/70">{fmtNum(hi)}</span>
    </span>
  );
}

export default function WeiPage() {
  const [rows, setRows] = useState<BoardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string>(""); // "" = latest close; YYYY-MM-DD = backdated board

  // Re-fetch whenever the as-of date changes. Newest-wins (the `alive` guard) so a slow earlier load
  // can't clobber a newer one. An as-of date backdates the whole board (server resolves last session
  // ≤ date, per index); empty ⇒ latest. Future/empty dates resolve to latest server-side.
  useEffect(() => {
    let alive = true;
    const qs = asOf ? `?as_of_date=${encodeURIComponent(asOf)}` : "";
    fetch(`/api/sym/indexes/board${qs}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`board -> ${r.status}`))))
      .then((d: BoardRow[]) => {
        if (alive) {
          setRows(d);
          setError(null);
        }
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [asOf]);

  // board freshness anchor = the most recent session across all indices; rows behind it are stale.
  const boardDate = useMemo(
    () => (rows ?? []).reduce<string | null>((mx, r) => (r.last_date && (!mx || r.last_date > mx) ? r.last_date : mx), null),
    [rows],
  );
  const grouped = useMemo(() => {
    const by = new Map<string, BoardRow[]>();
    for (const r of rows ?? []) (by.get(r.region) ?? by.set(r.region, []).get(r.region)!).push(r);
    for (const list of by.values())
      list.sort((a, b) => Math.abs(b.chg_pct ?? 0) - Math.abs(a.chg_pct ?? 0)); // biggest movers first
    return REGION_ORDER.filter((rg) => by.has(rg)).map((rg) => [rg, by.get(rg)!] as const);
  }, [rows]);

  return (
    <div className="w-full">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h1 className="text-lg font-semibold text-fg">World equity indices</h1>
        <p className="grow text-xs text-muted">
          Major equity indices by region — last level, 1-day change, YTD.
        </p>
        <div className="flex items-center gap-2">
          {boardDate ? (
            <span className="text-xs text-muted">
              EOD · as of {boardDate}
              {asOf && boardDate !== asOf ? " (backdated)" : ""}
            </span>
          ) : null}
          <label className="flex items-center gap-1 text-xs text-muted" title="Rewind the board to a past close">
            <span className="sr-only">As of date</span>
            <input
              type="date"
              value={asOf}
              max={boardDate && !asOf ? boardDate : undefined}
              onChange={(e) => setAsOf(e.target.value)}
              className="rounded border border-border bg-bg px-1.5 py-0.5 text-xs text-fg"
            />
          </label>
          {asOf ? (
            <button
              type="button"
              onClick={() => setAsOf("")}
              className="rounded border border-border px-1.5 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg"
            >
              Latest
            </button>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-rose-500">
          Could not load the board: {error}
        </p>
      ) : rows == null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">
          No index level data yet. Seed indices with <code className="rounded bg-fg/10 px-1">sym msci-pull</code>{" "}
          or the benchmark loader.
        </p>
      ) : (
        // One table for the whole board so every column lines up across regions; each region is a
        // grouped <tbody> introduced by a full-width banner row.
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-xs [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
            <thead className="text-[10px] uppercase tracking-wide text-muted">
              <tr className="border-b border-border">
                <th className="px-2 py-1 text-left font-medium">Index</th>
                <th className="px-2 py-1 text-right font-medium">Last</th>
                <th className="px-2 py-1 text-right font-medium">1D</th>
                <th className="px-2 py-1 text-right font-medium">5D</th>
                <th className="px-2 py-1 text-right font-medium">MTD</th>
                <th className="px-2 py-1 text-right font-medium">1M</th>
                <th className="px-2 py-1 text-right font-medium">3M</th>
                <th className="px-2 py-1 text-right font-medium">6M</th>
                <th className="px-2 py-1 text-right font-medium">YTD</th>
                <th className="px-2 py-1 text-right font-medium">1Y</th>
                <th className="px-2 py-1 text-right font-medium">2Y</th>
                <th className="px-2 py-1 text-right font-medium">3Y</th>
                <th className="px-2 py-1 text-right font-medium">5Y</th>
                <th className="px-2 py-1 text-center font-medium">52w range</th>
                <th className="px-2 py-1 text-center font-medium">30d</th>
                <th className="px-2 py-1 text-right font-medium">Ccy</th>
              </tr>
            </thead>
            {grouped.map(([region, list]) => (
              <tbody key={region}>
                <tr className="bg-fg/5">
                  <th
                    colSpan={16}
                    className="border-y border-border/60 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-muted"
                  >
                    {region}
                  </th>
                </tr>
                {list.map((r) => {
                  const stale = r.last_date != null && boardDate != null && r.last_date < boardDate;
                  return (
                    <tr key={r.sym_id} className="border-b border-border/30 hover:bg-fg/5">
                      <td className="px-2 py-0.5 font-medium text-fg">
                        {r.name ?? `#${r.sym_id}`}
                        {stale ? (
                          <span className="ml-1 text-amber-500" title={`behind the latest session — as of ${r.last_date}`}>●</span>
                        ) : null}
                      </td>
                      <td className="px-2 py-0.5 text-right tabular-nums text-fg">{fmtNum(r.last)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.chg_pct)}`}>{fmtPct(r.chg_pct)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.d5)}`}>{fmtPct(r.d5)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.mtd)}`}>{fmtPct(r.mtd)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.m1)}`}>{fmtPct(r.m1)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.m3)}`}>{fmtPct(r.m3)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.m6)}`}>{fmtPct(r.m6)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r.ytd)}`}>{fmtPct(r.ytd)}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r["1y"])}`}>{fmtPct(r["1y"])}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r["2y"])}`}>{fmtPct(r["2y"])}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r["3y"])}`}>{fmtPct(r["3y"])}</td>
                      <td className={`px-2 py-0.5 text-right tabular-nums ${upDown(r["5y"])}`}>{fmtPct(r["5y"])}</td>
                      <td className="px-2 py-0.5 text-center"><Range52 lo={r.lo_52w} hi={r.hi_52w} last={r.last} /></td>
                      <td className="px-2 py-0.5 text-center"><Spark pts={r.spark} /></td>
                      <td className="px-2 py-0.5 text-right text-muted">{r.currency ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            ))}
          </table>
        </div>
      )}

      <p className="mt-3 text-[11px] leading-snug text-muted">
        EOD levels from the warehouse (1-day change = last vs prior session). Markets close on
        different calendars — rows marked <span className="text-amber-500">●</span> are behind the
        latest session. MSCI aggregates shown as Net Return. A QRP view, not affiliated with any vendor.
      </p>
    </div>
  );
}
