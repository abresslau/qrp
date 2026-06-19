"use client";

import { type MouseEvent as ReactMouseEvent, useEffect, useMemo, useState } from "react";

import type { Schemas } from "@/lib/api";

type SeriesSummary = Schemas["SeriesSummary"];
type SeriesDetail = Schemas["SeriesDetail"];

// Comparison overlays a same-(name, unit) group across countries. Enabled for the buckets
// whose World-Bank/OECD panels share an indicator name across geographies (a cross-country
// macro overlay — the sell-side staple). Categories of bespoke single-name series
// (fx/activity/commodities/markets/debt) have no comparable group and render none.
export const COMPARISON_CATEGORIES = [
  "inflation",
  "gdp",
  "rates",
  "employment",
  "trade",
  "money",
  "population",
];

// Fixed palette; index-stable per chart so a toggled-off line keeps its colour on return.
const PALETTE = [
  "#0ea5e9", // sky
  "#f59e0b", // amber
  "#10b981", // emerald
  "#f43f5e", // rose
  "#8b5cf6", // violet
  "#06b6d4", // cyan
  "#84cc16", // lime
  "#d946ef", // fuchsia
];

type Group = { name: string; unit: string | null; members: SeriesSummary[] };
type Loaded = { summary: SeriesSummary; detail: SeriesDetail };

// A comparison chart caps at the top-N members by latest value (and fetches detail only for
// those). Keeps a global-coverage indicator like population (217 countries) from drawing
// hundreds of lines / firing hundreds of detail requests; every existing panel is ≤28.
const MAX_COMPARE_MEMBERS = 30;

/** Same-indicator series (matching name AND unit — one honest axis) with ≥2 members; each
 *  group capped to the largest MAX_COMPARE_MEMBERS by latest value. */
function groupComparable(series: SeriesSummary[]): Group[] {
  const by = new Map<string, Group>();
  for (const s of series) {
    const key = `${s.name}\u0000${s.unit ?? ""}`;
    const g = by.get(key) ?? { name: s.name, unit: s.unit, members: [] };
    g.members.push(s);
    by.set(key, g);
  }
  return [...by.values()]
    .filter((g) => g.members.length >= 2)
    .map((g) =>
      g.members.length <= MAX_COMPARE_MEMBERS
        ? g
        : {
            ...g,
            members: [...g.members]
              .sort((a, b) => (b.latest ?? -Infinity) - (a.latest ?? -Infinity))
              .slice(0, MAX_COMPARE_MEMBERS),
          },
    );
}

function fmt(v: number, unit?: string | null): string {
  return `${v.toFixed(2)}${unit?.includes("%") ? "%" : ""}`;
}

// value of a series nearest to timestamp t (its observations are date-sorted)
function valueAt(obs: { obs_date: string; value: number }[], t: number): number | null {
  if (obs.length === 0) return null;
  let best = obs[0];
  let bestD = Infinity;
  for (const o of obs) {
    const d = Math.abs(new Date(o.obs_date).getTime() - t);
    if (d < bestD) {
      bestD = d;
      best = o;
    }
  }
  return best.value;
}

function CompareChart({ group, loaded }: { group: Group; loaded: Loaded[] }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hoverT, setHoverT] = useState<number | null>(null);

  const plottable = useMemo(
    () => loaded.filter((l) => l.detail.observations.length >= 2),
    [loaded]
  );
  const visible = useMemo(
    () => plottable.filter((l) => !hidden.has(l.summary.series_id)),
    [plottable, hidden]
  );

  const { lines, lo, hi, x0, x1, minX, maxX } = useMemo(() => {
    if (visible.length === 0)
      return { lines: [], lo: 0, hi: 0, x0: "", x1: "", minX: 0, maxX: 1 };
    const W = 720;
    const H = 240;
    const PAD = 28;
    const all = visible.flatMap((l) =>
      l.detail.observations.map((o) => ({ t: new Date(o.obs_date).getTime(), v: o.value }))
    );
    const minX = Math.min(...all.map((p) => p.t));
    const maxX = Math.max(...all.map((p) => p.t));
    const minY = Math.min(...all.map((p) => p.v));
    const maxY = Math.max(...all.map((p) => p.v));
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const sx = (t: number) => PAD + ((t - minX) / spanX) * (W - 2 * PAD);
    const sy = (v: number) => H - PAD - ((v - minY) / spanY) * (H - 2 * PAD);
    const lines = visible.map((l) => ({
      id: l.summary.series_id,
      d: l.detail.observations
        .map(
          (o, i) =>
            `${i ? "L" : "M"}${sx(new Date(o.obs_date).getTime()).toFixed(1)},${sy(o.value).toFixed(1)}`
        )
        .join(" "),
    }));
    return {
      lines,
      lo: minY,
      hi: maxY,
      x0: new Date(minX).getFullYear().toString(),
      x1: new Date(maxX).getFullYear().toString(),
      minX,
      maxX,
    };
  }, [visible]);

  const W = 720;
  const PAD = 28;
  const hoverX =
    hoverT != null ? PAD + ((hoverT - minX) / (maxX - minX || 1)) * (W - 2 * PAD) : null;
  const onMove = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (visible.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * W;
    const frac = Math.min(1, Math.max(0, (vbX - PAD) / (W - 2 * PAD)));
    setHoverT(minX + frac * (maxX - minX));
  };

  // colour by position in the GROUP (stable from the summaries), not in `plottable` —
  // out-of-order detail loads must not reshuffle colours mid-load
  const colorOf = (id: string) =>
    PALETTE[group.members.findIndex((m) => m.series_id === id) % PALETTE.length];

  const toggle = (id: string) => {
    setHidden((h) => {
      if (!h.has(id) && visible.length === 1) return h; // refuse hiding the last line
      const next = new Set(h);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between">
        <div className="font-medium text-fg">{group.name}</div>
        <div className="text-xs text-muted">
          {hoverT != null
            ? new Date(hoverT).toLocaleDateString("en-US", { year: "numeric", month: "short" })
            : group.unit}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {loaded.map((l) => {
          // fetched-but-unplottable (<2 obs) series stay VISIBLE as disabled chips —
          // never silently missing from the comparison they belong to
          const short = l.detail.observations.length < 2;
          const off = hidden.has(l.summary.series_id);
          return (
            <button
              key={l.summary.series_id}
              type="button"
              disabled={short}
              onClick={() => toggle(l.summary.series_id)}
              className={[
                "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition",
                short || off
                  ? "border-border text-muted opacity-50"
                  : "border-border text-fg hover:bg-fg/5",
              ].join(" ")}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: colorOf(l.summary.series_id) }}
              />
              {l.summary.geo}
              <span className="tabular-nums text-muted">
                {short
                  ? "not plottable"
                  : fmt(
                      (hoverT != null && !off
                        ? valueAt(l.detail.observations, hoverT)
                        : null) ?? l.detail.observations.at(-1)!.value,
                      group.unit
                    )}
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-3">
        <svg
          viewBox="0 0 720 240"
          className="w-full"
          onMouseMove={onMove}
          onMouseLeave={() => setHoverT(null)}
        >
          {hoverX != null && (
            <line
              x1={hoverX}
              x2={hoverX}
              y1={12}
              y2={228}
              className="text-fg/40"
              stroke="currentColor"
              strokeWidth={0.8}
            />
          )}
          {lines.map((ln) => (
            <path
              key={ln.id}
              d={ln.d}
              fill="none"
              stroke={colorOf(ln.id)}
              strokeWidth={1.6}
            />
          ))}
        </svg>
        <div className="flex justify-between text-xs text-muted">
          <span>{x0}</span>
          <span>
            range {fmt(lo, group.unit)} – {fmt(hi, group.unit)}
          </span>
          <span>{x1}</span>
        </div>
      </div>
    </div>
  );
}

/** Comparison charts for a category: one multi-line chart per same-(name, unit) group.
 *  Mount keyed by category (the parent does this) so a category switch remounts cleanly. */
export function MacroCompare({
  category,
  series,
}: {
  category: string;
  series: SeriesSummary[];
}) {
  const groups = useMemo(() => groupComparable(series), [series]);
  const wanted = useMemo(
    () => groups.flatMap((g) => g.members.map((m) => m.series_id)),
    [groups]
  );

  const [loaded, setLoaded] = useState<Map<string, Loaded>>(new Map());
  const [failed, setFailed] = useState<{ id: string; geo: string }[]>([]);

  useEffect(() => {
    if (wanted.length === 0) return;
    let stale = false;
    const byId = new Map(
      series.filter((s) => wanted.includes(s.series_id)).map((s) => [s.series_id, s])
    );
    wanted.forEach((id) => {
      fetch(`/api/macro/series/${id}`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
        .then((d: SeriesDetail) => {
          if (stale) return;
          setLoaded((m) => new Map(m).set(id, { summary: byId.get(id)!, detail: d }));
        })
        .catch(() => {
          if (stale) return;
          // a failed line is DROPPED and NAMED — never silently missing
          setFailed((f) => [...f, { id, geo: byId.get(id)?.geo ?? id }]);
        });
    });
    return () => {
      stale = true;
    };
  }, [wanted, series]);

  // pending/failed are DERIVED from settled ids (no setState-in-effect counters)
  const failedWanted = failed.filter((f) => wanted.includes(f.id));
  const pending = wanted.length - wanted.filter((id) => loaded.has(id)).length - failedWanted.length;

  if (groups.length === 0) return null;

  return (
    <div className="mb-5 space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-fg">Compare</h2>
        <span className="text-xs text-muted">
          {pending > 0
            ? `loading ${pending} series…`
            : failedWanted.length > 0
              ? `couldn’t load: ${failedWanted.map((f) => f.geo).join(", ")}`
              : `${category} · ${groups.length} chart${groups.length > 1 ? "s" : ""}`}
        </span>
      </div>
      {groups.map((g) => {
        const got = g.members
          .map((m) => loaded.get(m.series_id))
          .filter((l): l is Loaded => l !== undefined);
        // gate on PLOTTABLE members (≥2 obs), not merely fetched ones — two 1-obs
        // series must not render an empty junk chart
        if (got.filter((l) => l.detail.observations.length >= 2).length < 2) return null;
        return <CompareChart key={`${g.name}|${g.unit}`} group={g} loaded={got} />;
      })}
    </div>
  );
}
