"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { Composition } from "@/components/portfolio-heatmap";
import { fmtPrice } from "@/lib/format";
import { qualifiedTicker, type TickerConvention } from "@/lib/ticker";
import { useTickerConvention } from "@/lib/ticker-convention";

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

type Mover = {
  ticker: string;
  ret: number | null;
  contribution: number;
  weight?: number | null;
  price?: number | null; // live price (when available) — appended to the hover sparkline
  figi?: string;
  currency?: string | null;
  // exchange codes for the region-qualified ticker (Bloomberg region / venue, FactSet region)
  exch_code?: string | null;
  bbg_exchange_code?: string | null;
  country_iso?: string | null;
};
type Bar = { session_date: string; close: number | null };

function pct(r: number | null): string {
  return r == null ? "—" : `${r >= 0 ? "+" : ""}${(r * 100).toFixed(2)}%`;
}
// Portfolio weight, signed (− for shorts), 2dp.
function wpct(w: number | null | undefined): string {
  return w == null ? "—" : `${w >= 0 ? "" : "−"}${(Math.abs(w) * 100).toFixed(2)}%`;
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
      weight: h.weight,
      price: h.price,
      figi: h.figi,
      currency: h.currency,
      exch_code: h.exch_code ?? null,
      bbg_exchange_code: h.bbg_exchange_code ?? null,
      country_iso: h.country_iso ?? null,
    }));
}

// 1Y price sparkline (close line) with the LIVE price appended as the final point when available —
// so the line ends at the live mark, not yesterday's close. Coloured by net direction over the window.
function Sparkline({ bars, live }: { bars: Bar[]; live?: number | null }) {
  const closes = bars.filter((b) => b.close != null).map((b) => b.close as number);
  const ys = live != null && Number.isFinite(live) ? [...closes, live] : closes;
  if (ys.length < 2) return <div className="text-[11px] text-muted">No price history.</div>;
  const W = 220;
  const H = 56;
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const x = (i: number) => (i / (ys.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / (max - min || 1)) * H;
  const d = ys.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
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
  convention,
  onEnter,
  onLeave,
}: {
  m: Mover;
  i: number;
  metric: Metric;
  convention: TickerConvention;
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
        {qualifiedTicker(m, convention)}
      </span>
      <span className="w-12 shrink-0 text-right tabular-nums text-[11px] text-muted">{wpct(m.weight)}</span>
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
  label,
  tone,
  convention,
  onEnter,
  onLeave,
}: {
  rows: Mover[];
  empty: string;
  metric: Metric;
  label: string; // e.g. "Top 10 winners" — lives IN the column header row (saves a heading line)
  tone: string; // colour class for the label (emerald winners / rose losers)
  convention: TickerConvention; // region-qualified ticker convention (shared store)
  onEnter: (m: Mover, e: React.MouseEvent) => void;
  onLeave: () => void;
}) {
  return (
    <>
      {/* Column header: the winners/losers label sits where the ticker column starts, replacing a
          standalone <h4> heading row — same info, ~1 row shorter. */}
      <div className="flex items-baseline gap-2 text-[10px] uppercase tracking-wide text-muted">
        <span className="w-4 shrink-0" aria-hidden />
        <span className={`flex-1 truncate font-semibold ${tone}`}>{label}</span>
        <span className="w-12 shrink-0 text-right">wt</span>
        <span className={`w-14 shrink-0 text-right ${metric === "% CHG" ? "text-fg" : ""}`}>% chg</span>
        <span className={`w-16 shrink-0 text-right ${metric === "P&L" ? "text-fg" : ""}`}>contrib</span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-xs text-muted">{empty}</p>
      ) : (
        <ol className="mt-0.5 space-y-0.5 text-xs">
          {rows.map((m, i) => (
            <Row key={m.ticker} m={m} i={i} metric={metric} convention={convention} onEnter={onEnter} onLeave={onLeave} />
          ))}
        </ol>
      )}
    </>
  );
}

export function PortfolioMovers({ pid, composition }: { pid: string; composition: Composition | null }) {
  const [win, setWin] = useState<Win>("Daily");
  const [metric, setMetric] = useState<Metric>("P&L");
  const convention = useTickerConvention(); // shared region-qualified ticker convention (one subscription)
  const [windowMovers, setWindowMovers] = useState<Mover[] | null>(null); // MTD/YTD (fetched); null while loading
  const [err, setErr] = useState<string | null>(null);

  // ticker -> {figi, currency, exchange codes} from the composition, so MTD/YTD movers (which arrive
  // ticker-only) can resolve a figi for the sparkline fetch AND the region-qualified ticker.
  const byTicker = useMemo(() => {
    const m = new Map<
      string,
      { figi: string; currency: string | null; price: number | null; exch_code: string | null; bbg_exchange_code: string | null; country_iso: string | null }
    >();
    for (const h of composition?.holdings ?? [])
      if (h.ticker)
        m.set(h.ticker, {
          figi: h.figi,
          currency: h.currency,
          price: h.price ?? null,
          exch_code: h.exch_code ?? null,
          bbg_exchange_code: h.bbg_exchange_code ?? null,
          country_iso: h.country_iso ?? null,
        });
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
  // Show the LIVE price when available, falling back to the last EOD close.
  const hoverLive = hover?.m.price ?? null;
  const hoverPrice = hoverLive ?? lastClose;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted">Movers</h3>
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

      {/* Compact: no reserved min-height — the card hugs its content (no empty space below the
          lists), leaving vertical room for a sibling card. It may shift a little when the window
          toggle changes the winner/loser counts; that's the trade for zero dead space. */}
      <div className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
        <div>
          {loading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : (
            <List
              rows={winners}
              empty={err ?? "No gainers in this window."}
              metric={metric}
              label={`Top ${TOP_N} winners`}
              tone="text-emerald-600 dark:text-emerald-400"
              convention={convention}
              onEnter={onEnter}
              onLeave={() => setHover(null)}
            />
          )}
        </div>
        {/* vertical divider between winners and losers (only when side-by-side at sm+) */}
        <div className="sm:border-l sm:border-border sm:pl-4">
          {loading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : (
            <List
              rows={losers}
              empty={err ?? "No decliners in this window."}
              metric={metric}
              label={`Top ${TOP_N} losers`}
              tone="text-rose-600 dark:text-rose-400"
              convention={convention}
              onEnter={onEnter}
              onLeave={() => setHover(null)}
            />
          )}
        </div>
      </div>
      {hover?.m.figi && (
        <div
          className="pointer-events-none fixed z-50 w-64 rounded-lg border border-border bg-bg p-3 text-fg shadow-xl"
          style={{ left: Math.min(hover.x + 14, (typeof window !== "undefined" ? window.innerWidth : 1200) - 272), top: hover.y + 14 }}
        >
          <div className="flex items-baseline justify-between">
            <span className="font-semibold">{qualifiedTicker(hover.m, convention)}</span>
            <span className="text-xs tabular-nums text-muted">
              {hover.m.currency ?? ""} {fmtPrice(hoverPrice, hover.m.currency)}
            </span>
          </div>
          {hoverBars === undefined ? (
            <div className="mt-2 text-[11px] text-muted">Loading 1Y price…</div>
          ) : (
            <Sparkline bars={hoverBars} live={hoverLive} />
          )}
          <div className="mt-1 text-[10px] uppercase tracking-wide text-muted">
            1Y price · {hoverLive != null ? "live" : "close"}
          </div>
        </div>
      )}
    </div>
  );
}
