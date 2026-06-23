"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

// Three at-a-glance market-snapshot cards for the Data Monitor: a mini rates curve, the headline
// equity index, and the major USD FX legs. Each fetches independently and degrades to an honest
// "unavailable" without taking the others (or the freshness table beneath) down, and links to its
// full page. Snapshot only — the authoritative views live at /rates, /sym/indices, /monitor/fx.

type CurvePt = { tenor: number; value: number };
type Curve = { country: string; rate_type: string; as_of_date: string | null; points: CurvePt[] };
type BoardRow = { name: string | null; last: number | null; chg_pct: number | null; last_date: string | null; spark: number[] };
type FxCell = { rate: number | null; chg: number | null; stale: boolean; pair: string };
type FxRow = { base: string; cells: FxCell[] };
type FxMatrix = { as_of_date: string; currencies: string[]; rows: FxRow[] };

const UP = "text-emerald-600 dark:text-emerald-400";
const DOWN = "text-red-600 dark:text-red-400";
const STROKE = "text-fg/45";

function pctClass(v: number | null | undefined): string {
  return v == null ? "text-muted" : v > 0 ? UP : v < 0 ? DOWN : "text-muted";
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}

// Inline sparkline / curve: a polyline scaled into a small viewBox. < 2 finite points → nothing.
function Spark({ values, w = 132, h = 34 }: { values: number[]; w?: number; h?: number }) {
  const xs = values.filter((v) => Number.isFinite(v));
  if (xs.length < 2) return <div style={{ height: h }} />;
  const min = Math.min(...xs);
  const max = Math.max(...xs);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / span) * h}`)
    .join(" ");
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={STROKE}>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.5}
        vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function Card({
  href, title, subtitle, children, loading, error,
}: {
  href: string; title: string; subtitle?: string; children: React.ReactNode;
  loading: boolean; error: boolean;
}) {
  return (
    <Link
      href={href}
      className="group flex flex-col rounded-xl border border-border bg-surface p-3 transition hover:bg-fg/5 2xl:p-4"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-fg">{title}</span>
        <span className="text-xs text-muted">{subtitle}</span>
      </div>
      <div className="mt-2 min-h-[3.25rem]">
        {loading ? (
          <div className="text-xs text-muted">Loading…</div>
        ) : error ? (
          <div className="text-xs text-muted/70">unavailable</div>
        ) : (
          children
        )}
      </div>
    </Link>
  );
}

type State<T> = { data: T | null; loading: boolean; error: boolean };
const INIT = { data: null, loading: true, error: false };

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export function DataSnapshotCards() {
  const [rates, setRates] = useState<State<Curve>>(INIT);
  const [idx, setIdx] = useState<State<BoardRow>>(INIT);
  const [fx, setFx] = useState<State<{ matrix: FxMatrix; legs: { ccy: string; cell: FxCell }[] }>>(INIT);

  useEffect(() => {
    let alive = true;
    // Rates: the default (GB) latest nominal-spot curve.
    getJson<Curve>("/api/rates/curve")
      .then((d) => alive && setRates({ data: d, loading: false, error: false }))
      .catch(() => alive && setRates({ data: null, loading: false, error: true }));

    // Indices: the headline equity index (S&P 500, else the first board row).
    getJson<BoardRow[]>("/api/sym/indices/board")
      .then((rows) => {
        const row = rows.find((r) => r.name === "S&P 500") ?? rows[0] ?? null;
        if (alive) setIdx({ data: row, loading: false, error: row == null });
      })
      .catch(() => alive && setIdx({ data: null, loading: false, error: true }));

    // FX: the major legs per 1 USD (EUR / JPY / GBP).
    getJson<FxMatrix>("/api/sym/fx/matrix?currencies=USD,EUR,JPY,GBP")
      .then((m) => {
        const usd = m.rows.find((r) => r.base === "USD");
        const legs = ["EUR", "JPY", "GBP"]
          .map((ccy) => {
            const i = m.currencies.indexOf(ccy);
            return usd && i >= 0 ? { ccy, cell: usd.cells[i] } : null;
          })
          .filter((x): x is { ccy: string; cell: FxCell } => x != null && x.cell?.rate != null);
        if (alive) setFx({ data: { matrix: m, legs }, loading: false, error: !usd || legs.length === 0 });
      })
      .catch(() => alive && setFx({ data: null, loading: false, error: true }));

    return () => {
      alive = false;
    };
  }, []);

  // Rates headline: the 10y point (nearest tenor), and the curve drawn across tenors.
  const r = rates.data;
  const tenY = r?.points?.length
    ? r.points.reduce((a, b) => (Math.abs(b.tenor - 10) < Math.abs(a.tenor - 10) ? b : a))
    : null;

  const ix = idx.data;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card href="/rates" title="Rates curves"
        subtitle={r ? `${r.country} · ${r.as_of_date ?? ""}` : undefined}
        loading={rates.loading} error={rates.error}>
        {r && (
          <>
            <Spark values={r.points.map((p) => p.value)} />
            <div className="mt-1 text-sm tabular-nums text-fg">
              10y <span className="font-semibold">{tenY ? `${tenY.value.toFixed(2)}%` : "—"}</span>
            </div>
          </>
        )}
      </Card>

      <Card href="/sym/indices" title="Indices"
        subtitle={ix?.last_date ?? undefined} loading={idx.loading} error={idx.error}>
        {ix && (
          <>
            <Spark values={ix.spark ?? []} />
            <div className="mt-1 flex items-baseline gap-2">
              <span className="truncate text-xs text-muted">{ix.name}</span>
              <span className="text-sm font-semibold tabular-nums text-fg">
                {ix.last != null ? ix.last.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
              </span>
              <span className={`text-xs tabular-nums ${pctClass(ix.chg_pct)}`}>{fmtPct(ix.chg_pct)}</span>
            </div>
          </>
        )}
      </Card>

      <Card href="/monitor/fx" title="FX rates"
        subtitle={fx.data ? `per USD · ${fx.data.matrix.as_of_date}` : undefined}
        loading={fx.loading} error={fx.error}>
        {fx.data && (
          <div className="space-y-1">
            {fx.data.legs.map(({ ccy, cell }) => (
              <div key={ccy} className="flex items-baseline justify-between text-sm">
                <span className="text-xs text-muted">{ccy}</span>
                <span className="tabular-nums text-fg">
                  {cell.rate!.toLocaleString(undefined, { maximumFractionDigits: ccy === "JPY" ? 2 : 4 })}
                </span>
                <span className={`text-xs tabular-nums ${pctClass(cell.chg)}`}>{fmtPct(cell.chg)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
