"use client";

// UK rates — the fixed-income curve view. Derive-on-read over rates.curve_point (BoE curves):
// a curve chart (spot/forward × nominal/real/inflation + OIS) plus spread monitors (2s10s, fly,
// breakeven, asset-swap) with z-score/percentile context and a click-through history chart.
// EOD-only (a live mark is a later story). Theme-aware via currentColor; SSR-safe; newest-wins fetch.

import { useEffect, useMemo, useRef, useState } from "react";

import { axisTickCount, dateAxisTicks, tickAnchor } from "@/lib/date-axis";

type CurvePoint = { tenor: number; value: number };
type Curve = {
  curve_set: string;
  basis: string;
  rate_type: string;
  vintage: string;
  as_of_date: string | null;
  points: CurvePoint[];
};
type SparkPoint = { as_of_date: string; value: number };
type Spread = {
  key: string;
  label: string;
  unit: string; // "bp" | "%"
  value: number | null;
  zscore: number | null;
  percentile: number | null;
  as_of_date: string | null;
  history: SparkPoint[];
};
type SpreadHistory = { key: string; label: string; unit: string; points: SparkPoint[] };

type CurveSet = "glc" | "ois";
type Basis = "nominal" | "real" | "inflation";
type RateType = "spot" | "forward";

const fmtVal = (v: number | null | undefined, unit: string): string => {
  if (v == null || !Number.isFinite(v)) return "N/A";
  return unit === "bp" ? `${v >= 0 ? "+" : ""}${v.toFixed(1)} bp` : `${v.toFixed(2)}%`;
};
const fmtZ = (z: number | null | undefined): string =>
  z == null || !Number.isFinite(z) ? "—" : `${z >= 0 ? "+" : ""}${z.toFixed(2)}σ`;
const fmtPctile = (p: number | null | undefined): string =>
  p == null || !Number.isFinite(p) ? "—" : `${p.toFixed(0)}th`;

// --- curve chart: x = tenor (years, linear), y = rate (%). currentColor theme. -------------------
const W = 900;
const H = 300;
const PAD_L = 52;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 30;

function CurveChart({ points }: { points: CurvePoint[] }) {
  const geom = useMemo(() => {
    if (points.length < 2) return null;
    const xs = points.map((p) => p.tenor);
    const ys = points.map((p) => p.value);
    const xmin = Math.min(...xs);
    const xmax = Math.max(...xs);
    const ymin = Math.min(...ys);
    const ymax = Math.max(...ys);
    const yspan = ymax - ymin || 1;
    const xspan = xmax - xmin || 1;
    const X = (t: number) => PAD_L + ((t - xmin) / xspan) * (W - PAD_L - PAD_R);
    const Y = (v: number) => PAD_T + (1 - (v - ymin) / yspan) * (H - PAD_T - PAD_B);
    const line = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${X(p.tenor).toFixed(1)},${Y(p.value).toFixed(1)}`)
      .join(" ");
    const yticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ v: ymin + f * yspan, yy: Y(ymin + f * yspan) }));
    // tenor ticks at sensible round years within range
    const cand = [0.5, 1, 2, 5, 10, 15, 20, 30, 40];
    const xticks = cand.filter((t) => t >= xmin && t <= xmax).map((t) => ({ x: X(t), label: `${t}y` }));
    return { X, Y, line, yticks, xticks };
  }, [points]);

  if (!geom) return <p className="text-sm text-muted">No curve published for this selection.</p>;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full text-fg" role="img" aria-label="Yield curve">
      {geom.yticks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} x2={W - PAD_R} y1={t.yy} y2={t.yy} stroke="currentColor" strokeOpacity={0.12} />
          <text x={PAD_L - 8} y={t.yy + 3} textAnchor="end" className="fill-muted" fontSize={11}>
            {t.v.toFixed(2)}%
          </text>
        </g>
      ))}
      <path d={geom.line} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" />
      {geom.xticks.map((t, i) => (
        <text key={i} x={t.x} y={H - 9} textAnchor="middle" className="fill-muted" fontSize={11}>
          {t.label}
        </text>
      ))}
    </svg>
  );
}

// --- mini sparkline (no axes) for a spread's recent history --------------------------------------
function Sparkline({ points }: { points: SparkPoint[] }) {
  const d = useMemo(() => {
    if (points.length < 2) return null;
    const vs = points.map((p) => p.value);
    const min = Math.min(...vs);
    const max = Math.max(...vs);
    const span = max - min || 1;
    const n = points.length;
    return points
      .map((p, i) => {
        const x = (i / (n - 1)) * 100;
        const y = 24 - ((p.value - min) / span) * 22 - 1;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [points]);
  if (!d) return null;
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="h-6 w-full text-muted" aria-hidden>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// --- spread history chart (date axis via lib/date-axis) ------------------------------------------
function HistoryChart({ hist }: { hist: SpreadHistory }) {
  const geom = useMemo(() => {
    const s = hist.points;
    if (s.length < 2) return null;
    const vs = s.map((p) => p.value);
    const min = Math.min(...vs);
    const max = Math.max(...vs);
    const span = max - min || 1;
    const n = s.length;
    const x = (i: number) => PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R);
    const y = (v: number) => PAD_T + (1 - (v - min) / span) * (H - PAD_T - PAD_B);
    const line = s.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
    const yticks = [0, 0.5, 1].map((f) => ({ v: min + f * span, yy: y(min + f * span) }));
    const times = s.map((p) => new Date(p.as_of_date).getTime());
    const xticks = dateAxisTicks(times[0], times[n - 1], axisTickCount(W - PAD_L - PAD_R)).map((tk) => {
      let idx = 0;
      let best = Infinity;
      for (let i = 0; i < times.length; i++) {
        const dd = Math.abs(times[i] - tk.t);
        if (dd < best) {
          best = dd;
          idx = i;
        }
      }
      return { x: x(idx), label: tk.label };
    });
    return { line, yticks, xticks };
  }, [hist]);
  if (!geom) return <p className="text-sm text-muted">Not enough history to chart.</p>;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full text-fg" role="img" aria-label="Spread history">
      {geom.yticks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} x2={W - PAD_R} y1={t.yy} y2={t.yy} stroke="currentColor" strokeOpacity={0.12} />
          <text x={PAD_L - 8} y={t.yy + 3} textAnchor="end" className="fill-muted" fontSize={11}>
            {hist.unit === "bp" ? t.v.toFixed(0) : t.v.toFixed(2)}
          </text>
        </g>
      ))}
      <path d={geom.line} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round" />
      {geom.xticks.map((t, i) => (
        <text key={i} x={t.x} y={H - 9} textAnchor={tickAnchor(i)} className="fill-muted" fontSize={11}>
          {t.label}
        </text>
      ))}
    </svg>
  );
}

function Seg<T extends string>({ value, options, onChange }: { value: T; options: readonly T[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          onClick={() => onChange(o)}
          className={`px-2.5 py-1 capitalize ${value === o ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

export default function RatesPage() {
  const [curveSet, setCurveSet] = useState<CurveSet>("glc");
  const [basis, setBasis] = useState<Basis>("nominal");
  const [rateType, setRateType] = useState<RateType>("spot");
  const [curve, setCurve] = useState<Curve | null>(null);
  const [curveErr, setCurveErr] = useState<string | null>(null);
  const curveAbort = useRef<AbortController | null>(null);

  const [spreads, setSpreads] = useState<Spread[] | null>(null);
  const [selKey, setSelKey] = useState<string | null>(null);
  const [hist, setHist] = useState<SpreadHistory | null>(null);
  const [histWindow, setHistWindow] = useState<"1Y" | "5Y" | "MAX">("MAX");
  const histAbort = useRef<AbortController | null>(null);

  // OIS publishes nominal only — keep the basis valid when switching curve sets.
  useEffect(() => {
    if (curveSet === "ois" && basis !== "nominal") setBasis("nominal");
  }, [curveSet, basis]);

  useEffect(() => {
    curveAbort.current?.abort();
    const ac = new AbortController();
    curveAbort.current = ac;
    // OIS publishes nominal only — clamp here so no request is issued for an unpublished
    // (ois, real/inflation) combo on the frame before the correcting effect settles `basis`.
    const effBasis = curveSet === "ois" ? "nominal" : basis;
    const qs = `curve_set=${curveSet}&basis=${effBasis}&rate_type=${rateType}`;
    void (async () => {
      setCurveErr(null);
      try {
        const r = await fetch(`/api/rates/curve?${qs}`, { cache: "no-store", signal: ac.signal });
        if (!r.ok) throw new Error(`curve -> ${r.status}`);
        const d: Curve = await r.json();
        if (!ac.signal.aborted) setCurve(d);
      } catch (e) {
        if (!ac.signal.aborted) setCurveErr(String(e));
      }
    })();
    return () => ac.abort();
  }, [curveSet, basis, rateType]);

  useEffect(() => {
    let alive = true;
    fetch("/api/rates/spreads", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`spreads -> ${r.status}`))))
      .then((rows: Spread[]) => alive && setSpreads(rows))
      .catch(() => alive && setSpreads([]));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (selKey == null) return;
    histAbort.current?.abort();
    const ac = new AbortController();
    histAbort.current = ac;
    void (async () => {
      try {
        const r = await fetch(`/api/rates/spread/${selKey}?window=${histWindow}`, { cache: "no-store", signal: ac.signal });
        if (!r.ok) throw new Error(`${r.status}`);
        const d: SpreadHistory = await r.json();
        if (!ac.signal.aborted) setHist(d);
      } catch {
        /* keep prior */
      }
    })();
    return () => ac.abort();
  }, [selKey, histWindow]);

  const bases: Basis[] = curveSet === "ois" ? ["nominal"] : ["nominal", "real", "inflation"];

  return (
    <div className="w-full">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-fg">UK rates</h1>
        <p className="mt-1 text-sm text-muted">
          Bank of England gilt &amp; SONIA/OIS curves (EOD). Spreads, breakeven and carry are derived on
          read from the stored curve — nothing here is a separate dataset.
        </p>
      </header>

      <section className="mb-5 rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Seg value={curveSet} options={["glc", "ois"] as const} onChange={setCurveSet} />
          <Seg value={basis} options={bases} onChange={setBasis} />
          <Seg value={rateType} options={["spot", "forward"] as const} onChange={setRateType} />
          <span className="ml-auto text-xs text-muted">
            {curve?.as_of_date ? `as of ${curve.as_of_date}` : ""}
          </span>
        </div>
        {curveErr ? (
          <p className="text-sm text-rose-500">Could not load curve: {curveErr}</p>
        ) : (
          <CurveChart points={curve?.points ?? []} />
        )}
        <div className="mt-1 text-right text-xs text-muted">
          {curveSet.toUpperCase()} {basis} {rateType} · % per annum (continuously compounded)
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Spread monitors</h2>
        {spreads == null ? (
          <p className="text-sm text-muted">Loading spreads…</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            {spreads.map((s) => {
              const active = s.key === selKey;
              const tone =
                s.value == null ? "text-muted" : s.value >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
              return (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSelKey(active ? null : s.key)}
                  className={`rounded-xl border p-3 text-left transition ${
                    active ? "border-fg/40 bg-fg/5" : "border-border bg-surface hover:border-fg/30"
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-xs text-muted">{s.label}</span>
                    <span className={`text-lg font-semibold tabular-nums ${tone}`}>{fmtVal(s.value, s.unit)}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted">
                    <span>z {fmtZ(s.zscore)}</span>
                    <span>{fmtPctile(s.percentile)} pctile</span>
                  </div>
                  <div className="mt-2">
                    <Sparkline points={s.history} />
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {selKey && hist ? (
          <div className="mt-4 rounded-xl border border-border bg-surface p-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-medium text-fg">
                {hist.label} <span className="text-muted">({hist.unit})</span>
              </div>
              <div className="inline-flex overflow-hidden rounded-md border border-border text-xs">
                {(["1Y", "5Y", "MAX"] as const).map((w) => (
                  <button
                    key={w}
                    type="button"
                    onClick={() => setHistWindow(w)}
                    className={`px-2 py-0.5 ${histWindow === w ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"}`}
                  >
                    {w}
                  </button>
                ))}
              </div>
            </div>
            <HistoryChart hist={hist} />
          </div>
        ) : null}
      </section>

      <p className="mt-4 text-xs text-muted">
        Source: Bank of England published yield curves (Open Government Licence). Breakeven is RPI-based
        (lagged), not CPI. Asset-swap is a gilt-yield−OIS proxy. EOD; derive-on-read.
      </p>
    </div>
  );
}
