"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Composition } from "@/components/portfolio-heatmap";
import { fmtPrice } from "@/lib/format";

// Top 10 winners / losers ranked by P&L CONTRIBUTION (weight × return) over the chosen window.
// Daily = the live composition (Σ contribution rolls up to the top Daily P&L — same source as the
// heat map / donut). MTD/YTD = the snapshot-attribution endpoint (current holdings × window return).
// Hovering a ticker pops a tooltip with a 1Y price sparkline (fetched on demand, cached).
type Win = "Daily" | "MTD" | "YTD";
const WINDOWS: Win[] = ["Daily", "MTD", "YTD"];
type Metric = "P&L" | "% CHG";
const METRICS: Metric[] = ["P&L", "% CHG"];
const TOP_N = 10;
const SPARK_DAYS = 365;

type Mover = { ticker: string; ret: number | null; contribution: number; figi?: string; currency?: string | null };
type Bar = { session_date: string; close: number | null };

function pct(r: number | null): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
function tone(r: number): string {
  return r >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

function dailyMovers(comp: Composition | null): Mover[] {
  if (!comp?.holdings?.length) return [];
  return comp.holdings
    .filter((h) => h.live_return != null)
    .map((h) => ({
      ticker: h.ticker ?? h.figi,
      ret: h.live_return,
      contribution: h.weight * (h.live_return as number),
      figi: h.figi,
      currency: h.currency,
    }));
}

// 1Y price sparkline (close-only line, colored by net direction over the window).
function Sparkline({ bars }: { bars: Bar[] }) {
  const pts = bars.filter((b) => b.close != null);
  if (pts.length < 2) return <div className="text-[11px] text-muted">No price history.</div>;
  const W = 220;
  const H = 56;
  const ys = pts.map((b) => b.close as number);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const x = (i: number) => (i / (pts.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / (max - min || 1)) * H;
  const d = pts.map((b, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(b.close as number).toFixed(1)}`).join("");
  const up = ys[ys.length - 1] >= ys[0];
  const col = up ? "#10b981" : "#ef4444";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-1 block w-full" preserveAspectRatio="none" aria-hidden>
      <path d={`${d}L${W},${H}L0,${H}Z`} fill={col} fillOpacity={0.12} />
      <path d={d} fill="none" stroke={col} strokeWidth={1.5} />
    </svg>
  );
}

function Row({
  m,
  i,
  metric,
  onEnter,
  onLeave,
}: {
  m: Mover;
  i: number;
  metric: Metric;
  onEnter: (m: Mover, e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  const hoverable = !!m.figi;
  // The ranked-by column is emphasised (bold + colored); the other is muted.
  const chgActive = metric === "% CHG";
  return (
    <li className="flex items-baseline gap-2">
      <span className="w-4 shrink-0 text-right text-[11px] tabular-nums text-muted">{i + 1}</span>
      <span
        className={`flex-1 truncate font-medium text-fg ${hoverable ? "cursor-help underline decoration-dotted decoration-muted/50 underline-offset-2" : ""}`}
        onMouseEnter={hoverable ? (e) => onEnter(m, e) : undefined}
        onMouseMove={hoverable ? (e) => onEnter(m, e) : undefined}
        onMouseLeave={hoverable ? onLeave : undefined}
      >
        {m.ticker}
      </span>
      <span
        className={`w-14 shrink-0 text-right tabular-nums ${chgActive ? `text-xs font-semibold ${m.ret == null ? "text-muted" : tone(m.ret)}` : "text-[11px] text-muted"}`}
      >
        {pct(m.ret)}
      </span>
      <span
        className={`w-16 shrink-0 text-right tabular-nums ${chgActive ? "text-[11px] text-muted" : `text-xs font-semibold ${tone(m.contribution)}`}`}
      >
        {pct(m.contribution)}
      </span>
    </li>
  );
}

function List({
  rows,
  empty,
  metric,
  onEnter,
  onLeave,
}: {
  rows: Mover[];
  empty: string;
  metric: Metric;
  onEnter: (m: Mover, e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  return (
    <>
      <div className="mt-2 flex items-baseline gap-2 text-[10px] uppercase tracking-wide text-muted">
        <span className="w-4 shrink-0" aria-hidden />
        <span className="flex-1" />
        <span className={`w-14 shrink-0 text-right ${metric === "% CHG" ? "text-fg" : ""}`}>% chg</span>
        <span className={`w-16 shrink-0 text-right ${metric === "P&L" ? "text-fg" : ""}`}>contrib</span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-muted">{empty}</p>
      ) : (
        <ol className="mt-1 space-y-1 text-sm">
          {rows.map((m, i) => (
            <Row key={m.ticker} m={m} i={i} metric={metric} onEnter={onEnter} onLeave={onLeave} />
          ))}
        </ol>
      )}
    </>
  );
}

export function PortfolioMovers({ pid, composition }: { pid: string; composition: Composition | null }) {
  const [win, setWin] = useState<Win>("Daily");
  const [metric, setMetric] = useState<Metric>("P&L");
  const [windowMovers, setWindowMovers] = useState<Mover[] | null>(null); // MTD/YTD (fetched); null while loading
  const [err, setErr] = useState<string | null>(null);

  // ticker -> {figi, currency} from the composition, so MTD/YTD movers (which arrive ticker-only) can
  // still resolve a figi for the sparkline fetch.
  const byTicker = useMemo(() => {
    const m = new Map<string, { figi: string; currency: string | null }>();
    for (const h of composition?.holdings ?? []) if (h.ticker) m.set(h.ticker, { figi: h.figi, currency: h.currency });
    return m;
  }, [composition]);

  useEffect(() => {
    if (win === "Daily") return; // Daily comes from the composition prop, no fetch
    const ac = new AbortController();
    void (async () => {
      setWindowMovers(null);
      setErr(null);
      try {
        const r = await fetch(`/api/portfolios/${pid}/returns?window=${win}`, { cache: "no-store", signal: ac.signal });
        if (!r.ok) throw new Error(`returns ${r.status}`);
        const d: { constituents?: Mover[] } = await r.json();
        if (!ac.signal.aborted) {
          const rows = (d.constituents ?? []).map((c) => ({ ...c, ...byTicker.get(c.ticker) }));
          setWindowMovers(rows);
        }
      } catch {
        if (!ac.signal.aborted) {
          setErr("couldn't load");
          setWindowMovers([]);
        }
      }
    })();
    return () => ac.abort();
  }, [pid, win, byTicker]);

  const all = win === "Daily" ? dailyMovers(composition) : windowMovers;

  const { winners, losers } = useMemo(() => {
    const rows = all ?? [];
    // Rank by the selected metric: P&L contribution (weight × return) or the holding's % change.
    const key = (m: Mover) => (metric === "P&L" ? m.contribution : m.ret);
    const valued = rows.filter((m) => key(m) != null) as Mover[];
    const winners = valued.filter((m) => (key(m) as number) > 0).sort((a, b) => (key(b) as number) - (key(a) as number)).slice(0, TOP_N);
    const losers = valued.filter((m) => (key(m) as number) < 0).sort((a, b) => (key(a) as number) - (key(b) as number)).slice(0, TOP_N);
    return { winners, losers };
  }, [all, metric]);

  const loading = all === null;

  // --- ticker hover: a 1Y price sparkline, fetched on demand and cached ---
  const [hover, setHover] = useState<{ m: Mover; x: number; y: number } | null>(null);
  const [cache, setCache] = useState<Record<string, Bar[]>>({});
  const inflight = useRef<Set<string>>(new Set());

  function onEnter(m: Mover, e: React.MouseEvent) {
    setHover({ m, x: e.clientX, y: e.clientY });
    const figi = m.figi;
    if (!figi || figi in cache || inflight.current.has(figi)) return;
    inflight.current.add(figi);
    void (async () => {
      try {
        const r = await fetch(`/api/sym/securities/${figi}/prices?days=${SPARK_DAYS}`, { cache: "no-store" });
        const d: Bar[] = r.ok ? await r.json() : [];
        setCache((prev) => ({ ...prev, [figi]: d }));
      } catch {
        setCache((prev) => ({ ...prev, [figi]: [] }));
      } finally {
        inflight.current.delete(figi);
      }
    })();
  }

  const hoverBars = hover?.m.figi ? cache[hover.m.figi] : undefined;
  const lastClose = hoverBars?.filter((b) => b.close != null).at(-1)?.close ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted">Top movers</h3>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
            {METRICS.map((mt) => (
              <button
                key={mt}
                type="button"
                onClick={() => setMetric(mt)}
                className={`px-2 py-0.5 ${metric === mt ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
              >
                {mt}
              </button>
            ))}
          </div>
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => setWin(w)}
                className={`px-2 py-0.5 ${win === w ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
              >
                {w}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Fixed min-height (reserves room for TOP_N rows) so the card doesn't jump when the
          window toggle changes the number of winners/losers. */}
      <div className="mt-3 grid min-h-[19rem] content-start gap-4 sm:grid-cols-2">
        <div>
          <h4 className="text-[11px] font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
            Top {TOP_N} winners
          </h4>
          {loading ? (
            <p className="mt-2 text-xs text-muted">Loading…</p>
          ) : (
            <List rows={winners} empty={err ?? "No gainers in this window."} metric={metric} onEnter={onEnter} onLeave={() => setHover(null)} />
          )}
        </div>
        <div>
          <h4 className="text-[11px] font-medium uppercase tracking-wide text-rose-600 dark:text-rose-400">
            Top {TOP_N} losers
          </h4>
          {loading ? (
            <p className="mt-2 text-xs text-muted">Loading…</p>
          ) : (
            <List rows={losers} empty={err ?? "No decliners in this window."} metric={metric} onEnter={onEnter} onLeave={() => setHover(null)} />
          )}
        </div>
      </div>
      <p className="mt-2 text-[11px] text-muted">
        Ranked by {metric === "P&L" ? "P&L contribution (weight × return)" : "% change"}
        {win === "Daily" ? " · live (rolls up to Daily P&L)" : " · current holdings × window return"}.
      </p>

      {hover?.m.figi && (
        <div
          className="pointer-events-none fixed z-50 w-64 rounded-lg border border-border bg-bg p-3 text-fg shadow-xl"
          style={{ left: Math.min(hover.x + 14, (typeof window !== "undefined" ? window.innerWidth : 1200) - 272), top: hover.y + 14 }}
        >
          <div className="flex items-baseline justify-between">
            <span className="font-semibold">{hover.m.ticker}</span>
            <span className="text-xs tabular-nums text-muted">
              {hover.m.currency ?? ""} {fmtPrice(lastClose, hover.m.currency)}
            </span>
          </div>
          {hoverBars === undefined ? (
            <div className="mt-2 text-[11px] text-muted">Loading 1Y price…</div>
          ) : (
            <Sparkline bars={hoverBars} />
          )}
          <div className="mt-1 text-[10px] uppercase tracking-wide text-muted">1Y price · close</div>
        </div>
      )}
    </div>
  );
}
