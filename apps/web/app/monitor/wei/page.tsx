"use client";

// World Equity Indices (WEI) — a regional board of the major equity indices from index_levels:
// last level, 1-day net/% change, YTD, and an inline sparkline, colour-coded up/down. EOD (1D = last
// vs prior session); per-market staleness is marked (markets close on different calendars). A
// QRP-native take on the classic global-equity monitor — sourced entirely from our own warehouse.

import { useEffect, useMemo, useState } from "react";

import { ScaleToFit } from "@/components/scale-to-fit";
import { useOnline } from "@/lib/connection";

type BoardRow = {
  sym_id: number;
  name: string | null;
  region: string;
  country: string;
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
  freshness?: string; // LIVE mode only: live | delayed | unavailable
  quote_time?: string | null;
};
type LiveMeta = { as_of: string | null; freshness: string; priced: number; total: number };

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

// LIVE-mode freshness → colour (live = fresh/emerald, delayed = amber, unavailable = muted).
const LIVE_TONE: Record<string, string> = {
  live: "text-emerald-500",
  delayed: "text-amber-500",
  unavailable: "text-muted",
};

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

// Board columns — drive the header + the sort accessor. The body cells stay explicit (each has its
// own formatting/colour). `val` is the sort key; `spark` is not sortable. 52w range sorts by where
// the level sits in its range (0 = at the low, 1 = at the high).
type SortVal = number | string | null;
type Col = { id: string; label: string; align: "left" | "right" | "center"; sortable: boolean; val: (r: BoardRow) => SortVal };
const range52Pos = (r: BoardRow): number | null =>
  r.lo_52w != null && r.hi_52w != null && r.last != null && r.hi_52w > r.lo_52w
    ? (r.last - r.lo_52w) / (r.hi_52w - r.lo_52w)
    : null;
const COLS: Col[] = [
  { id: "name", label: "Index", align: "left", sortable: true, val: (r) => r.name },
  { id: "country", label: "Country", align: "left", sortable: true, val: (r) => r.country },
  { id: "last", label: "Last", align: "right", sortable: true, val: (r) => r.last },
  { id: "chg_pct", label: "1D", align: "right", sortable: true, val: (r) => r.chg_pct },
  { id: "d5", label: "5D", align: "right", sortable: true, val: (r) => r.d5 },
  { id: "mtd", label: "MTD", align: "right", sortable: true, val: (r) => r.mtd },
  { id: "m1", label: "1M", align: "right", sortable: true, val: (r) => r.m1 },
  { id: "m3", label: "3M", align: "right", sortable: true, val: (r) => r.m3 },
  { id: "m6", label: "6M", align: "right", sortable: true, val: (r) => r.m6 },
  { id: "ytd", label: "YTD", align: "right", sortable: true, val: (r) => r.ytd },
  { id: "1y", label: "1Y", align: "right", sortable: true, val: (r) => r["1y"] },
  { id: "2y", label: "2Y", align: "right", sortable: true, val: (r) => r["2y"] },
  { id: "3y", label: "3Y", align: "right", sortable: true, val: (r) => r["3y"] },
  { id: "5y", label: "5Y", align: "right", sortable: true, val: (r) => r["5y"] },
  { id: "range", label: "52w range", align: "center", sortable: true, val: range52Pos },
  { id: "spark", label: "30d", align: "center", sortable: false, val: () => null },
  { id: "currency", label: "Ccy", align: "right", sortable: true, val: (r) => r.currency },
];
type SortDir = "asc" | "desc";
const ALIGN_CLS = { left: "text-left", right: "text-right", center: "text-center" } as const;

// Sort within a region group. Nulls/missing always sink to the bottom regardless of direction;
// text keys compare lexicographically, numeric keys numerically. Ties always break by index name
// ascending — so sorting by Country gives "country, then index name", and equal returns stay tidy.
function compareRows(a: BoardRow, b: BoardRow, key: string, dir: SortDir): number {
  const col = COLS.find((c) => c.id === key) ?? COLS[0];
  const va = col.val(a);
  const vb = col.val(b);
  let d = 0;
  if (va == null && vb == null) d = 0;
  else if (va == null) return 1;
  else if (vb == null) return -1;
  else d = typeof va === "string" || typeof vb === "string" ? String(va).localeCompare(String(vb)) : va - vb;
  const primary = dir === "asc" ? d : -d;
  if (primary !== 0 || key === "name") return primary;
  return String(a.name ?? "").localeCompare(String(b.name ?? "")); // tiebreak: index name asc
}

const maxLastDate = (rows: BoardRow[]): string | null =>
  rows.reduce<string | null>((mx, r) => (r.last_date && (!mx || r.last_date > mx) ? r.last_date : mx), null);

export default function WeiPage() {
  const [rows, setRows] = useState<BoardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string>(""); // "" = latest close; YYYY-MM-DD = backdated board
  const [latestDate, setLatestDate] = useState<string>(""); // newest session of the un-backdated board
  const [sort, setSort] = useState<{ key: string; dir: SortDir }>({ key: "country", dir: "asc" });
  const [mode, setMode] = useState<"EOD" | "LIVE">("EOD"); // LIVE = intraday quotes (best-effort, not stored)
  const [live, setLive] = useState<LiveMeta | null>(null); // LIVE rollup (worst freshness + as_of + coverage)
  const [nonce, setNonce] = useState(0); // bump to force a LIVE re-fetch (↻ refresh / auto-refresh tick)
  const [loading, setLoading] = useState(false);
  const [autoSec, setAutoSec] = useState(0); // LIVE auto-refresh interval in seconds; 0 = off
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null); // local clock of the last LIVE pull
  const online = useOnline(); // sidebar offline toggle pauses LIVE auto-refresh

  // Re-fetch on mode / as-of / refresh. Newest-wins via AbortController so a slow earlier load can't
  // clobber a newer one (QH.8). EOD: an as-of date backdates the board (server resolves last session ≤
  // date, per index); empty ⇒ latest; on a latest load capture the newest session for the picker bound.
  // LIVE: fetch the live board (intraday quotes re-marked onto the EOD windows) + its freshness rollup;
  // as-of is EOD-only (LIVE is "now"). Quotes are best-effort and never persisted.
  useEffect(() => {
    const ac = new AbortController();
    const url =
      mode === "LIVE"
        ? "/api/sym/indices/board/live"
        : `/api/sym/indices/board${asOf ? `?as_of_date=${encodeURIComponent(asOf)}` : ""}`;
    fetch(url, { cache: "no-store", signal: ac.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`board -> ${r.status}`))))
      .then((d) => {
        // clear the refresh spinner on every settle (incl. a superseded/aborted request) so a rapid
        // toggle mid-refresh can't leave the ↻ button stuck disabled.
        setLoading(false);
        if (ac.signal.aborted) return;
        if (mode === "LIVE") {
          setRows(d.rows as BoardRow[]);
          setLive({ as_of: d.as_of, freshness: d.freshness, priced: d.priced, total: d.total });
          // stamp the LOCAL clock each LIVE pull so an auto-refresh shows visible confirmation even
          // when the data's own `as_of` (sim-clock) doesn't move.
          setRefreshedAt(new Date().toLocaleTimeString());
        } else {
          setRows(d as BoardRow[]);
          setLive(null);
          if (!asOf) setLatestDate(maxLastDate(d) ?? "");
        }
        setError(null);
      })
      .catch((e) => {
        setLoading(false);
        if (!ac.signal.aborted) setError(String(e));
      });
    return () => ac.abort();
  }, [mode, asOf, nonce]);

  // LIVE auto-refresh: while a positive interval is set, LIVE is selected, AND the app is online
  // (sidebar toggle), bump the refresh nonce on a timer (re-pulls via the effect above). setState lives
  // in the timer callback, not the effect body (react-hooks/set-state-in-effect). Floored at 3s to stay
  // polite; going offline / leaving LIVE clears the timer (deps). Mirrors the heatmap-view LIVE refresh.
  useEffect(() => {
    if (mode !== "LIVE" || autoSec <= 0 || !online) return;
    const id = setInterval(() => setNonce((n) => n + 1), Math.max(3, autoSec) * 1000);
    return () => clearInterval(id);
  }, [mode, autoSec, online]);

  // board freshness anchor = the most recent session across all returned rows; rows behind it are stale.
  const boardDate = useMemo(() => maxLastDate(rows ?? []), [rows]);
  const backdated = asOf !== "" && asOf !== latestDate;
  const grouped = useMemo(() => {
    const by = new Map<string, BoardRow[]>();
    for (const r of rows ?? []) (by.get(r.region) ?? by.set(r.region, []).get(r.region)!).push(r);
    for (const list of by.values()) list.sort((a, b) => compareRows(a, b, sort.key, sort.dir));
    return REGION_ORDER.filter((rg) => by.has(rg)).map((rg) => [rg, by.get(rg)!] as const);
  }, [rows, sort]);
  // Click a header to sort the whole board within each region; text defaults ascending, numbers descending.
  const TEXT_COLS = new Set(["name", "country", "currency"]); // default ascending; numbers descending
  const onSort = (id: string) =>
    setSort((s) =>
      s.key === id
        ? { key: id, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key: id, dir: TEXT_COLS.has(id) ? "asc" : "desc" },
    );

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <header className="mb-2 flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h1 className="text-base font-semibold text-fg">World equity indices</h1>
        <p className="grow text-xs text-muted">
          Major equity indices by region — last level, 1-day change, YTD.
        </p>
        <div className="flex items-center gap-2">
          {/* EOD ⟷ LIVE mode toggle */}
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs" role="group" aria-label="board mode">
            {(["EOD", "LIVE"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={`px-2 py-0.5 ${mode === m ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
              >
                {m}
              </button>
            ))}
          </div>
          {mode === "LIVE" ? (
            <>
              {live ? (
                <span
                  className={`text-xs ${LIVE_TONE[live.freshness] ?? "text-muted"}`}
                  title="Intraday index quotes — best-effort, never stored"
                >
                  ● LIVE · {live.freshness} · {live.priced}/{live.total} priced
                  {live.as_of ? ` · as of ${new Date(live.as_of).toLocaleTimeString()}` : ""}
                  {refreshedAt ? ` · refreshed ${refreshedAt}` : ""}
                </span>
              ) : null}
              <label
                className="flex items-center gap-1 text-xs text-muted"
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
                  className="w-12 rounded border border-border bg-bg px-1 py-0.5 text-xs text-fg"
                />
                s{autoSec > 0 ? ` (${Math.max(3, autoSec)}s)` : ""}
              </label>
              <button
                type="button"
                onClick={() => {
                  setLoading(true);
                  setNonce((n) => n + 1);
                }}
                disabled={loading}
                aria-label="Refresh live quotes"
                className="rounded border border-border px-1.5 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg disabled:opacity-50"
              >
                {loading ? "…" : "↻"}
              </button>
            </>
          ) : (
            <>
              {boardDate ? (
                <span className="text-xs text-muted">
                  EOD · as of {boardDate}
                  {backdated ? " (backdated)" : ""}
                </span>
              ) : null}
              <label className="flex items-center gap-1 text-xs text-muted" title="Rewind the board to a past close">
                <span className="sr-only">As of date</span>
                <input
                  type="date"
                  value={asOf || latestDate}
                  max={latestDate || undefined}
                  // picking the latest date is "latest" — keep asOf empty so we fetch the clean URL
                  onChange={(e) => setAsOf(e.target.value === latestDate ? "" : e.target.value)}
                  className="rounded border border-border bg-bg px-1.5 py-0.5 text-xs text-fg"
                />
              </label>
              {backdated ? (
                <button
                  type="button"
                  onClick={() => setAsOf("")}
                  className="rounded border border-border px-1.5 py-0.5 text-xs text-muted hover:bg-fg/5 hover:text-fg"
                >
                  Latest
                </button>
              ) : null}
            </>
          )}
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
        // Scale the whole board to fit the available height: it looks identical on a laptop and a large
        // screen (same layout, just larger) and never leaves dead space below. One table for the whole
        // board so every column lines up across regions; each region is a grouped <tbody>.
        <div className="min-h-0 flex-1">
          <ScaleToFit>
            <div className="rounded-lg border border-border bg-surface">
              <table className="text-xs leading-tight [&_td]:whitespace-nowrap [&_th]:whitespace-nowrap">
            <thead className="text-[10px] uppercase tracking-wide text-muted">
              <tr className="border-b border-border">
                {COLS.map((c) => {
                  const active = sort.key === c.id;
                  return (
                    <th key={c.id} className={`px-2 py-0.5 font-medium ${ALIGN_CLS[c.align]}`}>
                      {c.sortable ? (
                        <button
                          type="button"
                          onClick={() => onSort(c.id)}
                          aria-label={`Sort by ${c.label}`}
                          className={`uppercase hover:text-fg ${active ? "text-fg" : ""}`}
                        >
                          {c.label}
                          <span className="ml-0.5 inline-block w-2 text-fg">{active ? (sort.dir === "asc" ? "▲" : "▼") : ""}</span>
                        </button>
                      ) : (
                        c.label
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            {grouped.map(([region, list]) => (
              <tbody key={region}>
                <tr className="bg-fg/5">
                  <th
                    colSpan={17}
                    className="border-y border-border/60 px-2 py-0.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted"
                  >
                    {region}
                  </th>
                </tr>
                {list.map((r) => {
                  // EOD: mark an index whose latest session lags the board date. LIVE: mark a
                  // delayed/unavailable quote (a closed market or a per-index miss) — never imply live.
                  const stale = mode === "EOD" && r.last_date != null && boardDate != null && r.last_date < boardDate;
                  const liveMark = mode === "LIVE" && r.freshness != null && r.freshness !== "live";
                  return (
                    <tr key={r.sym_id} className="border-b border-border/30 hover:bg-fg/5">
                      <td className="px-2 py-0.5 font-medium text-fg">
                        {r.name ?? `#${r.sym_id}`}
                        {stale ? (
                          <span
                            className="ml-1 text-amber-500"
                            title={`No session on ${boardDate} — showing the last close, ${r.last_date} (this market's calendar lags the board date)`}
                          >
                            ●
                          </span>
                        ) : null}
                        {liveMark ? (
                          <span
                            className={`ml-1 ${LIVE_TONE[r.freshness!] ?? "text-muted"}`}
                            title={
                              r.freshness === "unavailable"
                                ? "No live quote — showing the EOD close (market closed or quote unavailable)"
                                : `Delayed quote${r.quote_time ? ` · as of ${new Date(r.quote_time).toLocaleTimeString()}` : ""}`
                            }
                          >
                            ●
                          </span>
                        ) : null}
                      </td>
                      <td className="px-2 py-0.5 text-muted">{r.country}</td>
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
          </ScaleToFit>
        </div>
      )}

      <p className="mt-2 shrink-0 text-[10px] leading-snug text-muted">
        {mode === "LIVE" ? (
          <>
            LIVE intraday quotes — best-effort, <strong>never stored</strong>; 1D = live vs the latest
            close, windows re-based to the live mark. <span className="text-amber-500">●</span> delayed
            / <span className="text-muted">●</span> unavailable (closed market or no quote — shows the
            EOD close). In this environment the simulated clock makes quotes read{" "}
            <em>delayed</em>; the data still updates each refresh. MSCI shown as Net Return.
          </>
        ) : (
          <>
            EOD warehouse levels (1D = last vs prior session). <span className="text-amber-500">●</span> =
            no session on the board date — showing the prior close (date beside ●). MSCI shown as Net Return.
          </>
        )}
      </p>
    </div>
  );
}
