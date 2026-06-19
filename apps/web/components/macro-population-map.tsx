"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { WORLD_H, WORLD_PATHS, WORLD_W } from "@/lib/world-geo";

// World Bank population series carry a country *name* in `geo`; map the ones we track to ISO-A2
// (the key WORLD_PATHS uses). "Euro area" is an aggregate, not a country — it has no shape.
type Series = {
  series_id: string;
  category: string | null;
  geo: string | null;
  unit: string | null;
  latest: number | null;
  name: string;
};
type Row = { iso3: string; geo: string; total: number | null; growth: number | null };
type Metric = "total" | "growth";

function useIsDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const el = document.documentElement;
    const update = () => setDark(el.classList.contains("dark"));
    update();
    const obs = new MutationObserver(update);
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

type RGB = [number, number, number];
function mix(a: RGB, b: RGB, t: number): string {
  const c = (i: number) => Math.round(a[i] + (b[i] - a[i]) * Math.max(0, Math.min(1, t)));
  return `rgb(${c(0)},${c(1)},${c(2)})`;
}
function fmtPop(m: number | null): string {
  if (m == null) return "—";
  return m >= 1000 ? `${(m / 1000).toFixed(2)}B` : `${m.toFixed(1)}M`;
}
function fmtGrow(g: number | null): string {
  return g == null ? "—" : `${g >= 0 ? "+" : ""}${g.toFixed(2)}%/yr`;
}

export function MacroPopulationMap() {
  const isDark = useIsDark();
  const [metric, setMetric] = useState<Metric>("total");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hover, setHover] = useState<Row | null>(null);
  const [pos, setPos] = useState<{ x: number; y: number; w: number }>({ x: 0, y: 0, w: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await fetch("/api/macro/series", { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const all: Series[] = await r.json();
        const byIso = new Map<string, Row>();
        for (const s of all) {
          if (s.category !== "population") continue;
          // series_id is WB:SP.POP.TOTL:<ISO3> / WB:SP.POP.GROW:<ISO3>
          const iso3 = s.series_id.split(":").pop() ?? "";
          if (iso3.length !== 3) continue;
          const row = byIso.get(iso3) ?? { iso3, geo: s.geo ?? iso3, total: null, growth: null };
          if (s.series_id.includes("SP.POP.TOTL")) row.total = s.latest;
          else if (s.series_id.includes("SP.POP.GROW")) row.growth = s.latest;
          byIso.set(iso3, row);
        }
        if (alive) {
          setRows([...byIso.values()]);
          setLoading(false);
        }
      } catch (e) {
        if (alive) {
          setError(String(e));
          setLoading(false);
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const byIso = useMemo(() => {
    const m = new Map<string, Row>();
    for (const r of rows ?? []) m.set(r.iso3, r);
    return m;
  }, [rows]);

  // Total population is log-scaled (China & India dwarf the rest); growth is diverging about 0.
  const maxLogPop = useMemo(
    () => Math.log(Math.max(1, ...(rows ?? []).map((r) => r.total ?? 0)) + 1),
    [rows],
  );
  const GROWTH_CAP = 3; // %/yr — saturates the diverging ramp at ±3

  const ocean = isDark ? "#0c1118" : "#eaf0f6";
  const empty = isDark ? "#1c2530" : "#dde3ea";
  const popLo: RGB = isDark ? [22, 49, 46] : [209, 242, 235];
  const popHi: RGB = isDark ? [45, 212, 191] : [13, 118, 110];
  const negC: RGB = [244, 63, 94]; // rose — shrinking
  const midC: RGB = isDark ? [55, 65, 81] : [229, 231, 235];
  const posC: RGB = [16, 185, 129]; // emerald — growing

  function fillFor(r: Row | undefined): string {
    if (!r) return empty;
    if (metric === "total") {
      if (r.total == null) return empty;
      return mix(popLo, popHi, Math.log(r.total + 1) / maxLogPop);
    }
    if (r.growth == null) return empty;
    const t = Math.max(-1, Math.min(1, r.growth / GROWTH_CAP));
    return t >= 0 ? mix(midC, posC, t) : mix(midC, negC, -t);
  }

  const tracked = (rows ?? []).length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <div className="inline-flex overflow-hidden rounded-md border border-border">
          {([
            ["total", "Total population"],
            ["growth", "Growth"],
          ] as [Metric, string][]).map(([m, label]) => (
            <button
              key={m}
              type="button"
              onClick={() => setMetric(m)}
              className={`px-3 py-1 ${
                metric === m ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted">{tracked} countries · World Bank</span>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          Couldn&apos;t load population data: {error}
        </div>
      )}

      <div
        ref={containerRef}
        className="relative rounded-xl border border-border bg-surface p-2"
        onMouseMove={(e) => {
          const r = containerRef.current?.getBoundingClientRect();
          if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width });
        }}
        onMouseLeave={() => setHover(null)}
      >
        {loading && !rows && <div className="p-6 text-sm text-muted">Loading…</div>}
        <svg
          viewBox={`0 0 ${WORLD_W} ${WORLD_H}`}
          className="block w-full"
          role="img"
          aria-label="World map of population by country (World Bank)"
        >
          <rect x={0} y={0} width={WORLD_W} height={WORLD_H} fill={ocean} />
          {Object.entries(WORLD_PATHS).map(([iso, d]) => {
            const r = byIso.get(iso);
            const active = hover?.iso3 === iso;
            return (
              <path
                key={iso}
                d={d}
                fill={fillFor(r)}
                stroke={isDark ? "rgba(0,0,0,0.45)" : "rgba(255,255,255,0.7)"}
                strokeWidth={active ? 1.4 : 0.4}
                style={{ cursor: r ? "pointer" : "default" }}
                onMouseEnter={() => setHover(r ?? null)}
              />
            );
          })}
        </svg>

        {hover && (
          <div
            className="pointer-events-none absolute z-10 w-52 rounded-lg border border-border bg-bg/95 p-3 text-xs shadow-lg backdrop-blur"
            style={{ left: pos.x > pos.w - 220 ? pos.x - 210 : pos.x + 14, top: pos.y + 14 }}
          >
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold text-fg">{hover.geo}</span>
              <span className="font-mono text-[10px] text-muted">{hover.iso3}</span>
            </div>
            <div className="flex justify-between tabular-nums">
              <span className="text-muted">Population</span>
              <span className="text-fg">{fmtPop(hover.total)}</span>
            </div>
            <div className="flex justify-between tabular-nums">
              <span className="text-muted">Growth</span>
              <span
                className={
                  hover.growth == null
                    ? "text-fg"
                    : hover.growth >= 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-rose-600 dark:text-rose-400"
                }
              >
                {fmtGrow(hover.growth)}
              </span>
            </div>
          </div>
        )}

        <div className="absolute bottom-3 left-3 rounded-md border border-border bg-bg/85 px-2.5 py-1.5 text-[11px] backdrop-blur">
          {metric === "total" ? (
            <div className="flex items-center gap-2 text-muted">
              <span>fewer</span>
              <span
                className="h-2 w-24 rounded-full"
                style={{ background: `linear-gradient(90deg, ${mix(popLo, popHi, 0)}, ${mix(popLo, popHi, 1)})` }}
              />
              <span>more people</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-muted">
              <span className="text-rose-600 dark:text-rose-400">shrinking</span>
              <span
                className="h-2 w-24 rounded-full"
                style={{ background: `linear-gradient(90deg, ${mix(midC, negC, 1)}, ${mix(midC, midC, 0)}, ${mix(midC, posC, 1)})` }}
              />
              <span className="text-emerald-600 dark:text-emerald-400">growing</span>
            </div>
          )}
        </div>
      </div>

      <p className="mt-2 text-xs text-muted">
        Countries shaded by{" "}
        {metric === "total" ? "total population (log-scaled)" : "annual population growth"} — World Bank
        latest. Hover for the figures. Only the {tracked} tracked economies are shaded; the series are
        listed below.
      </p>
    </div>
  );
}
