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

// Historical comparison overlays: offset back from the latest curve date. The /curve endpoint
// resolves each target to the latest published curve on/before it (handles weekends/holidays).
type Offset = { days?: number; months?: number; years?: number };
const COMPARE_OFFSETS: { key: string; off: Offset; color: string }[] = [
  { key: "1D", off: { days: 1 }, color: "#0ea5e9" }, // sky
  { key: "1M", off: { months: 1 }, color: "#10b981" }, // emerald
  { key: "3M", off: { months: 3 }, color: "#f59e0b" }, // amber
  { key: "6M", off: { months: 6 }, color: "#a78bfa" }, // violet
  { key: "1Y", off: { years: 1 }, color: "#f43f5e" }, // rose
];

// timelapse speed presets (ms per frame; higher = slower)
const SPEEDS: { label: string; ms: number }[] = [
  { label: "0.5×", ms: 320 },
  { label: "1×", ms: 160 },
  { label: "2×", ms: 80 },
  { label: "4×", ms: 40 },
];

function offsetDate(isoLatest: string, off: Offset): string {
  const d = new Date(`${isoLatest}T00:00:00Z`);
  if (off.days) d.setUTCDate(d.getUTCDate() - off.days);
  if (off.months) d.setUTCMonth(d.getUTCMonth() - off.months);
  if (off.years) d.setUTCFullYear(d.getUTCFullYear() - off.years);
  return d.toISOString().slice(0, 10);
}

// --- curve chart: x = tenor (years, linear), y = rate (%). currentColor theme. -------------------
const W = 900;
const H = 300;
const PAD_L = 52;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 30;

// One curve to draw (the latest plus any historical comparison overlays).
type CurveLine = { points: CurvePoint[]; stroke: string; width: number; label: string; opacity?: number };
type Hover = { tenor: number; px: number; py: number; flip: boolean };

// linear interpolation of a curve's value at tenor t (for benchmark node markers); null outside range
function valueAtTenor(points: CurvePoint[], t: number): number | null {
  const pts = [...points].sort((a, b) => a.tenor - b.tenor);
  if (pts.length === 0 || t < pts[0].tenor || t > pts[pts.length - 1].tenor) return null;
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].tenor >= t) {
      const a = pts[i - 1];
      const b = pts[i];
      return b.tenor === a.tenor ? a.value : a.value + ((b.value - a.value) * (t - a.tenor)) / (b.tenor - a.tenor);
    }
  }
  return pts[pts.length - 1].value;
}

const tenorLabel = (t: number) => (t < 1 ? `${Math.round(t * 12)}m` : `${t}y`);

function CurveChart({
  lines,
  yDomain,
  xDomain,
  dateLabel,
  interactive = true,
}: {
  lines: CurveLine[];
  yDomain?: [number, number] | null;
  xDomain?: [number, number] | null;
  dateLabel?: string | null;
  interactive?: boolean;
}) {
  const [hover, setHover] = useState<Hover | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const geom = useMemo(() => {
    const all = lines.flatMap((l) => l.points);
    if (all.length < 2) return null;
    const xs = all.map((p) => p.tenor);
    const ys = all.map((p) => p.value);
    // fixed domains (timelapse) keep BOTH axes stable across frames; else fit to the data
    const xmin = xDomain ? xDomain[0] : Math.min(...xs);
    const xmax = xDomain ? xDomain[1] : Math.max(...xs);
    // y-axis: snap the data range to 0.50% gridlines (clean round ticks; curve still fills the frame)
    const YSTEP = 0.5;
    const rawMin = yDomain ? yDomain[0] : Math.min(...ys);
    const rawMax = yDomain ? yDomain[1] : Math.max(...ys);
    const ymin = Math.floor(rawMin / YSTEP) * YSTEP;
    const ymax = Math.max(ymin + YSTEP, Math.ceil(rawMax / YSTEP) * YSTEP);
    const yspan = ymax - ymin || 1;
    // √-scaled tenor axis (Bloomberg-style): gives the active short end room instead of cramming
    // it into the left edge under a linear-in-years axis. Not smoothing — segments join real nodes.
    const sx = (t: number) => Math.sqrt(Math.max(t, 0));
    const sxmin = sx(xmin);
    const sxspan = sx(xmax) - sxmin || 1;
    const X = (t: number) => PAD_L + ((sx(t) - sxmin) / sxspan) * (W - PAD_L - PAD_R);
    const Y = (v: number) => PAD_T + (1 - (v - ymin) / yspan) * (H - PAD_T - PAD_B);
    const paths = lines.map((l) => ({
      stroke: l.stroke,
      width: l.width,
      opacity: l.opacity ?? 1,
      d:
        l.points.length < 2
          ? ""
          : l.points
              .map((p, i) => `${i === 0 ? "M" : "L"}${X(p.tenor).toFixed(1)},${Y(p.value).toFixed(1)}`)
              .join(" "),
    }));
    const yticks: { v: number; yy: number }[] = [];
    for (let v = ymin; v <= ymax + 1e-9; v += YSTEP) yticks.push({ v, yy: Y(v) });
    // standard money-market + bond tenors; shown only where the selected curve actually has data
    // (gilts start ~5-6m — BoE doesn't fit them shorter; OIS/SONIA goes down to 1m).
    const cand = [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 40];
    const inRange = cand.filter((t) => t >= xmin - 1e-6 && t <= xmax + 1e-6);
    const xticks = inRange.map((t, i) => ({
      x: X(t),
      label: tenorLabel(t),
      anchor: i === 0 ? "start" : i === inRange.length - 1 ? "end" : "middle",
    }));
    // benchmark node markers on EVERY curve (latest + each comparison), in its own colour
    const markerSets = lines.map((l) => ({
      fill: l.stroke,
      r: l.width >= 1.8 ? 2.4 : 1.9, // latest a touch larger
      dots:
        (l.opacity ?? 1) < 1
          ? [] // ghost/reference lines get no markers
          : inRange
              .map((t) => {
                const v = valueAtTenor(l.points, t);
                return v == null ? null : { x: X(t), y: Y(v) };
              })
              .filter((m): m is { x: number; y: number } => m != null),
    }));
    return { paths, yticks, xticks, markerSets, X, Y, sxmin, sxspan, tickTenors: inRange };
  }, [lines, yDomain, xDomain]);

  if (!geom) return <p className="text-sm text-muted">No curve published for this selection.</p>;

  const g = geom; // narrowed for the handler/render below
  // comparison rows show their spread (bp) to the Latest line (found by label, since during a
  // timelapse the frame — not Latest — is the one drawn last).
  const latestLine = lines.find((l) => l.label === "Latest");
  const latestV = hover && latestLine ? valueAtTenor(latestLine.points, hover.tenor) : null;
  const allRows = hover
    ? lines
        .map((l) => {
          const v = valueAtTenor(l.points, hover.tenor);
          const isLatest = l.label === "Latest";
          return {
            label: l.label,
            color: l.stroke,
            v,
            diff: !isLatest && v != null && latestV != null ? v - latestV : null,
          };
        })
        .filter((r) => r.v != null)
    : [];
  // tooltip order: Latest first, then comparisons newest→oldest (1D,1M,3M,6M,1Y); draw order is unchanged.
  const latestRow = allRows.find((r) => r.label === "Latest");
  const hoverRows = latestRow
    ? [latestRow, ...allRows.filter((r) => r.label !== "Latest")]
    : allRows;
  const hx = hover ? g.X(hover.tenor) : 0;

  return (
    <div
      ref={wrapRef}
      className="relative"
      onMouseMove={(e) => {
        if (!interactive) return;
        const el = wrapRef.current;
        if (!el) return;
        const rect = el.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const py = e.clientY - rect.top;
        const vbX = (px / rect.width) * W;
        const frac = Math.min(1, Math.max(0, (vbX - PAD_L) / (W - PAD_L - PAD_R)));
        const sxv = g.sxmin + frac * g.sxspan;
        const tRaw = sxv * sxv;
        const tenor = g.tickTenors.reduce(
          (b, t) => (Math.abs(t - tRaw) < Math.abs(b - tRaw) ? t : b),
          g.tickTenors[0],
        );
        // only show when the cursor is actually ON a vertex (within ~12px of its column);
        // snap the crosshair exactly to it. Hovering between vertices shows nothing.
        const tenorPx = (g.X(tenor) / W) * rect.width;
        if (Math.abs(px - tenorPx) <= 12) {
          setHover({ tenor, px: tenorPx, py, flip: tenorPx > rect.width * 0.62 });
        } else if (hover) {
          setHover(null);
        }
      }}
      onMouseLeave={() => setHover(null)}
    >
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full text-fg" role="img" aria-label="Yield curve">
      {geom.yticks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} x2={W - PAD_R} y1={t.yy} y2={t.yy} stroke="currentColor" strokeOpacity={0.12} />
          <text x={PAD_L - 8} y={t.yy + 3} textAnchor="end" className="fill-muted" fontSize={11}>
            {t.v.toFixed(2)}%
          </text>
        </g>
      ))}
      {/* faint vertical gridlines at the benchmark tenors */}
      {geom.xticks.map((t, i) => (
        <line key={`g${i}`} x1={t.x} x2={t.x} y1={PAD_T} y2={H - PAD_B} stroke="currentColor" strokeOpacity={0.06} />
      ))}
      {/* big faint date in the top-right during the timelapse */}
      {dateLabel ? (
        <text
          x={W - PAD_R}
          y={PAD_T + 30}
          textAnchor="end"
          className="fill-fg"
          fontSize={30}
          fontWeight={700}
          opacity={0.22}
        >
          {dateLabel}
        </text>
      ) : null}
      {/* comparison overlays first, latest curve last (drawn on top) */}
      {geom.paths.map((p, i) =>
        p.d ? (
          <path
            key={i}
            d={p.d}
            fill="none"
            stroke={p.stroke}
            strokeWidth={p.width}
            strokeOpacity={p.opacity}
            strokeLinejoin="round"
          />
        ) : null,
      )}
      {/* benchmark node markers on every curve (overlays first, latest on top) */}
      {geom.markerSets.map((ms, li) =>
        ms.dots.map((m, i) => (
          <circle key={`m${li}-${i}`} cx={m.x} cy={m.y} r={ms.r} fill={ms.fill} />
        )),
      )}
      {geom.xticks.map((t, i) => (
        <text
          key={i}
          x={t.x}
          y={H - 9}
          textAnchor={t.anchor as "start" | "middle" | "end"}
          className="fill-muted"
          fontSize={11}
        >
          {t.label}
        </text>
      ))}
      {/* hover crosshair + a highlighted node on each curve at the cursor's tenor */}
      {interactive && hover ? (
        <g>
          <line
            x1={hx}
            x2={hx}
            y1={PAD_T}
            y2={H - PAD_B}
            stroke="currentColor"
            strokeOpacity={0.35}
            strokeDasharray="4 3"
          />
          {lines.map((l, i) => {
            const v = valueAtTenor(l.points, hover.tenor);
            return v == null ? null : <circle key={`h${i}`} cx={hx} cy={g.Y(v)} r={3.4} fill={l.stroke} />;
          })}
        </g>
      ) : null}
    </svg>
      {interactive && hover && hoverRows.length > 0 ? (
        <div
          className={`pointer-events-none absolute z-10 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs shadow-lg ${
            hover.flip ? "-translate-x-full" : ""
          }`}
          style={{ left: hover.px + (hover.flip ? -12 : 12), top: Math.max(0, hover.py - 10) }}
        >
          <div className="mb-1 font-medium text-fg">{tenorLabel(hover.tenor)}</div>
          {hoverRows.map((r, i) => (
            <div key={i} className="flex items-center justify-between gap-3 tabular-nums">
              <span className="flex items-center gap-1.5 text-muted">
                <span
                  className={`inline-block h-0.5 w-3 ${r.color === "currentColor" ? "bg-fg" : ""}`}
                  style={r.color === "currentColor" ? undefined : { backgroundColor: r.color }}
                />
                {r.label}
              </span>
              <span className="flex items-center gap-2">
                <span className="text-fg">{r.v!.toFixed(2)}%</span>
                {r.diff != null ? (
                  <span className="w-16 text-right text-muted">
                    {`${r.diff >= 0 ? "+" : "−"}${Math.abs(r.diff * 100).toFixed(0)} bp`}
                  </span>
                ) : (
                  <span className="w-16 text-right text-muted/50">ref</span>
                )}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
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
  const [compare, setCompare] = useState<Set<string>>(new Set());
  const [compareCurves, setCompareCurves] = useState<Record<string, Curve>>({});
  const cmpAbort = useRef<AbortController | null>(null);

  // timelapse: a "movie" of historical curves (oldest→latest) animated frame by frame
  type Frame = { as_of_date: string; points: CurvePoint[] };
  const [movie, setMovie] = useState<Frame[] | null>(null);
  const [playing, setPlaying] = useState(false);
  const [frameIdx, setFrameIdx] = useState(0);
  const [movieLoading, setMovieLoading] = useState(false);
  const [frameMs, setFrameMs] = useState(160); // ms per frame (speed); higher = slower
  const movieCache = useRef<Record<string, Frame[]>>({});

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

  // historical comparison overlays — fetch each active offset's curve (as-of the latest curve date
  // minus the offset). Re-runs when the selection changes (new series) or the toggle set changes.
  useEffect(() => {
    const anchor = curve?.as_of_date;
    if (!anchor || compare.size === 0) {
      setCompareCurves({});
      return;
    }
    cmpAbort.current?.abort();
    const ac = new AbortController();
    cmpAbort.current = ac;
    const effBasis = curveSet === "ois" ? "nominal" : basis;
    void (async () => {
      const got = await Promise.all(
        COMPARE_OFFSETS.filter((o) => compare.has(o.key)).map(async (o) => {
          const target = offsetDate(anchor, o.off);
          try {
            const r = await fetch(
              `/api/rates/curve?curve_set=${curveSet}&basis=${effBasis}&rate_type=${rateType}&as_of_date=${target}`,
              { cache: "no-store", signal: ac.signal },
            );
            if (!r.ok) return null;
            return [o.key, (await r.json()) as Curve] as const;
          } catch {
            return null;
          }
        }),
      );
      if (ac.signal.aborted) return;
      setCompareCurves(Object.fromEntries(got.filter(Boolean) as (readonly [string, Curve])[]));
    })();
    return () => ac.abort();
  }, [curve?.as_of_date, compare, curveSet, basis, rateType]);

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

  // drive the timelapse: advance one frame at a time; stop at the last (latest)
  useEffect(() => {
    if (!playing || !movie) return;
    if (frameIdx >= movie.length - 1) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => setFrameIdx((i) => i + 1), frameMs);
    return () => clearTimeout(id);
  }, [playing, movie, frameIdx, frameMs]);

  // the movie is series-specific — stop + clear it when the curve selection changes
  useEffect(() => {
    setPlaying(false);
    setMovie(null);
    setFrameIdx(0);
  }, [curveSet, basis, rateType]);

  const bases: Basis[] = curveSet === "ois" ? ["nominal"] : ["nominal", "real", "inflation"];

  const toggleCompare = (key: string) =>
    setCompare((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const onPlay = async () => {
    if (playing) {
      setPlaying(false); // pause — the current frame stays shown (freeze-frame)
      return;
    }
    if (movie) {
      // resume a paused timelapse from where it stopped (restart if parked at the end)
      if (frameIdx >= movie.length - 1) setFrameIdx(0);
      setPlaying(true);
      return;
    }
    if (!curve?.as_of_date) return;
    const effB = curveSet === "ois" ? "nominal" : basis;
    // window starts at the OLDEST selected comparison (e.g. 1Y → last year); default 1Y if none picked.
    const selected = COMPARE_OFFSETS.filter((o) => compare.has(o.key));
    const oldest = selected.length ? selected[selected.length - 1] : COMPARE_OFFSETS[COMPARE_OFFSETS.length - 1];
    const startDate = offsetDate(curve.as_of_date, oldest.off);
    const key = `${curveSet}/${effB}/${rateType}/${startDate}`;
    let mv = movieCache.current[key];
    if (!mv) {
      setMovieLoading(true);
      try {
        const r = await fetch(
          `/api/rates/curve/movie?curve_set=${curveSet}&basis=${effB}&rate_type=${rateType}&frames=120&start_date=${startDate}`,
          { cache: "no-store" },
        );
        if (!r.ok) throw new Error(`${r.status}`);
        mv = (await r.json()).frames as Frame[];
        movieCache.current[key] = mv;
      } catch {
        setMovieLoading(false);
        return;
      }
      setMovieLoading(false);
    }
    if (!mv || mv.length < 2) return;
    setMovie(mv);
    setFrameIdx(0);
    setPlaying(true);
  };

  // fixed axes for the timelapse so the curve moves within a stable frame (no per-frame rescale).
  // y spans ALL frames; x is the LATEST curve's tenor grid (the canonical span, not the union, so an
  // odd historical frame's extra short-end node can't add a phantom tick today's curve lacks).
  const movieDomains = useMemo<{ y: [number, number]; x: [number, number] } | null>(() => {
    if (!movie) return null;
    let ylo = Infinity;
    let yhi = -Infinity;
    const scanY = (pts: CurvePoint[]) => {
      for (const p of pts) {
        if (p.value < ylo) ylo = p.value;
        if (p.value > yhi) yhi = p.value;
      }
    };
    for (const f of movie) scanY(f.points);
    scanY(curve?.points ?? []);
    const ref = curve?.points?.length ? curve.points : (movie[movie.length - 1]?.points ?? []);
    let xlo = Infinity;
    let xhi = -Infinity;
    for (const p of ref) {
      if (p.tenor < xlo) xlo = p.tenor;
      if (p.tenor > xhi) xhi = p.tenor;
    }
    return Number.isFinite(ylo) && Number.isFinite(xlo) ? { y: [ylo, yhi], x: [xlo, xhi] } : null;
  }, [movie, curve]);

  // latest curve drawn last (on top, theme colour); active comparison overlays underneath.
  // during playback: a faint Latest ghost + the animating historical frame.
  const lines: CurveLine[] = useMemo(() => {
    if (movie && movie[frameIdx]) {
      // a loaded timelapse stays shown while paused (freeze-frame, like a movie) — not just while
      // playing. clip each frame to the canonical x-span so a frame's extra short-end node doesn't
      // draw past the axis (and the axis ticks always match the curve actually shown)
      const xd = movieDomains?.x;
      const raw = movie[frameIdx].points;
      const fp = xd ? raw.filter((p) => p.tenor >= xd[0] - 1e-9 && p.tenor <= xd[1] + 1e-9) : raw;
      return [
        // Latest keeps its normal theme colour during the animation (not a faint ghost)
        { points: curve?.points ?? [], stroke: "currentColor", width: 1.8, label: "Latest" },
        { points: fp, stroke: "#10b981", width: 2.4, label: movie[frameIdx].as_of_date },
      ];
    }
    const overlays = COMPARE_OFFSETS.filter((o) => compare.has(o.key) && compareCurves[o.key]).map(
      (o): CurveLine => ({ points: compareCurves[o.key].points, stroke: o.color, width: 1.3, label: o.key }),
    );
    return [
      ...overlays,
      { points: curve?.points ?? [], stroke: "currentColor", width: 1.8, label: "Latest" },
    ];
  }, [playing, movie, frameIdx, curve, compare, compareCurves, movieDomains]);

  return (
    <div className="w-full">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-fg">UK rates</h1>
        <p className="mt-1 text-sm text-muted">
          Bank of England gilt &amp; SONIA/OIS curves (EOD). Spreads, breakeven and carry are derived on
          read from the stored curve — nothing here is a separate dataset.
        </p>
      </header>

      <section className="relative mb-5 rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Seg value={curveSet} options={["glc", "ois"] as const} onChange={setCurveSet} />
          <Seg value={basis} options={bases} onChange={setBasis} />
          <Seg value={rateType} options={["spot", "forward"] as const} onChange={setRateType} />
          <button
            type="button"
            onClick={onPlay}
            disabled={movieLoading}
            className="w-28 rounded-md border border-border px-2.5 py-1 text-center text-xs text-fg transition hover:bg-fg/5 disabled:opacity-50"
          >
            {movieLoading ? "Loading…" : playing ? "⏸ Pause" : movie ? "▶ Play" : "▶ Timelapse"}
          </button>
          {movie ? (
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setMovie(null);
                setFrameIdx(0);
              }}
              title="exit timelapse"
              className="rounded-md border border-border px-2 py-1 text-xs text-muted transition hover:text-fg"
            >
              ✕
            </button>
          ) : null}
          <div className="inline-flex overflow-hidden rounded-md border border-border text-xs" title="timelapse speed">
            {SPEEDS.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => setFrameMs(s.ms)}
                className={`px-2 py-1 ${
                  frameMs === s.ms ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="mr-0.5 text-xs text-muted">vs</span>
            {COMPARE_OFFSETS.map((o) => {
              const on = compare.has(o.key);
              return (
                <button
                  key={o.key}
                  type="button"
                  onClick={() => toggleCompare(o.key)}
                  className={`rounded-md border px-2 py-0.5 text-xs tabular-nums transition ${
                    on ? "font-medium text-fg" : "border-border text-muted hover:text-fg"
                  }`}
                  style={on ? { borderColor: o.color, color: o.color } : undefined}
                  aria-pressed={on}
                >
                  {o.key}
                </button>
              );
            })}
          </div>
        </div>
        {curveErr ? (
          <p className="text-sm text-rose-500">Could not load curve: {curveErr}</p>
        ) : (
          <CurveChart
            lines={lines}
            yDomain={movie ? (movieDomains?.y ?? null) : null}
            xDomain={movie ? (movieDomains?.x ?? null) : null}
            dateLabel={movie ? (movie[frameIdx]?.as_of_date ?? null) : null}
            interactive={!playing}
          />
        )}
        {/* progress bar: absolute overlay on the card's bottom edge — takes no layout space; shown
            whenever a timelapse is loaded (playing or paused) so you can see the position */}
        {movie ? (
          <div className="absolute inset-x-0 bottom-0 h-1 overflow-hidden rounded-b-xl bg-fg/10">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${((frameIdx + 1) / movie.length) * 100}%` }}
            />
          </div>
        ) : null}
        {/* legend: latest + each active comparison with its resolved as-of date */}
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="flex items-center gap-1.5 text-fg">
            <span className="inline-block h-0.5 w-4 bg-current" />
            Latest{curve?.as_of_date ? ` · ${curve.as_of_date}` : ""}
          </span>
          {COMPARE_OFFSETS.filter((o) => compare.has(o.key)).map((o) => (
            <span key={o.key} className="flex items-center gap-1.5 text-muted">
              <span className="inline-block h-0.5 w-4" style={{ backgroundColor: o.color }} />
              {o.key}
              {compareCurves[o.key]?.as_of_date ? ` · ${compareCurves[o.key].as_of_date}` : " · …"}
            </span>
          ))}
        </div>
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
