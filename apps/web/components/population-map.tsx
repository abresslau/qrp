"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { WORLD_H, WORLD_PATHS, WORLD_W } from "@/lib/world-geo";

type Layer = { covered: number; total: number; latest_date: string | null; status: string };
type Country = {
  country_iso: string;
  country: string | null;
  timezone: string | null;
  members: number;
  active_members: number;
  prices: Layer;
  returns: Layer;
  fundamentals: Layer;
};
type UniverseRef = { universe_id: string; name: string | null };
type Mode = "population" | "coverage";
type LayerKey = "prices" | "returns" | "fundamentals";

// Mirror the heatmap's dark-mode observer so the palette tracks the theme toggle live.
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

export function PopulationMap({ universes }: { universes: UniverseRef[] }) {
  const isDark = useIsDark();
  const [uni, setUni] = useState<string>(""); // "" = whole tracked population
  const [mode, setMode] = useState<Mode>("population");
  const [layer, setLayer] = useState<LayerKey>("prices");
  const [data, setData] = useState<Country[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<Country | null>(null);
  const [pos, setPos] = useState<{ x: number; y: number; w: number }>({ x: 0, y: 0, w: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const url = `/api/sym/universes/coverage/by-country${uni ? `?universe=${encodeURIComponent(uni)}` : ""}`;
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) {
          const body = await r.json().catch(() => null);
          throw new Error(body?.error?.message ?? body?.detail ?? `HTTP ${r.status}`);
        }
        const d: Country[] = await r.json();
        if (alive) {
          setData(d);
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
  }, [uni]);

  const byIso = useMemo(() => {
    const m = new Map<string, Country>();
    for (const c of data ?? []) m.set(c.country_iso, c);
    return m;
  }, [data]);

  // Population shading is log-scaled (one market — the US — dwarfs the rest), so smaller
  // markets stay visible rather than washing out to the floor color.
  const maxLogPop = useMemo(() => {
    const mx = Math.max(1, ...(data ?? []).map((c) => c.active_members));
    return Math.log(mx + 1);
  }, [data]);

  const ocean = isDark ? "#0c1118" : "#eaf0f6";
  const empty = isDark ? "#1c2530" : "#dde3ea"; // a country with no tracked members
  const popLo: RGB = isDark ? [22, 49, 46] : [209, 242, 235];
  const popHi: RGB = isDark ? [45, 212, 191] : [13, 118, 110];
  const emerald: RGB = [16, 185, 129];
  const amber: RGB = [245, 158, 11];
  const rose: RGB = [244, 63, 94];

  function fillFor(c: Country | undefined): string {
    if (!c || c.active_members === 0) return empty;
    if (mode === "population") {
      return mix(popLo, popHi, Math.log(c.active_members + 1) / maxLogPop);
    }
    const L = c[layer];
    if (!L || L.total === 0) return empty;
    const p = L.covered / L.total;
    if (p <= 0) return `rgb(${rose[0]},${rose[1]},${rose[2]})`;
    if (p >= 1) return `rgb(${emerald[0]},${emerald[1]},${emerald[2]})`;
    return mix(amber, emerald, p); // partial: amber→emerald by coverage fraction
  }

  const totalMembers = (data ?? []).reduce((s, c) => s + c.members, 0);
  const totalActive = (data ?? []).reduce((s, c) => s + c.active_members, 0);

  const Pill = ({ s }: { s: string }) => {
    const cls =
      s === "ok"
        ? "text-emerald-600 dark:text-emerald-400"
        : s === "partial"
          ? "text-amber-600 dark:text-amber-400"
          : "text-rose-600 dark:text-rose-400";
    return <span className={`font-medium ${cls}`}>{s}</span>;
  };

  return (
    <div>
      {/* Controls */}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <select
          value={uni}
          onChange={(e) => setUni(e.target.value)}
          className="rounded-md border border-border bg-surface px-2 py-1 text-fg"
          aria-label="Universe"
        >
          <option value="">All tracked members</option>
          {universes.map((u) => (
            <option key={u.universe_id} value={u.universe_id}>
              {u.name ?? u.universe_id}
            </option>
          ))}
        </select>

        <div className="inline-flex overflow-hidden rounded-md border border-border">
          {(["population", "coverage"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`px-3 py-1 capitalize ${
                mode === m ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {mode === "coverage" && (
          <div className="inline-flex overflow-hidden rounded-md border border-border">
            {(["prices", "returns", "fundamentals"] as LayerKey[]).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLayer(l)}
                className={`px-2.5 py-1 capitalize ${
                  layer === l ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5"
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        )}

        <span className="ml-auto text-xs text-muted">
          {(data ?? []).length} countries · {totalActive.toLocaleString()} active
          {totalMembers !== totalActive ? ` / ${totalMembers.toLocaleString()} members` : ""}
        </span>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          Couldn&apos;t load the map: {error}
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
        {loading && !data && <div className="p-6 text-sm text-muted">Loading…</div>}
        <svg
          viewBox={`0 0 ${WORLD_W} ${WORLD_H}`}
          className="block w-full"
          role="img"
          aria-label="World map of universe population and coverage by country"
        >
          <rect x={0} y={0} width={WORLD_W} height={WORLD_H} fill={ocean} />
          {Object.entries(WORLD_PATHS).map(([iso, d]) => {
            const c = byIso.get(iso);
            const active = hover?.country_iso === iso;
            return (
              <path
                key={iso}
                d={d}
                fill={fillFor(c)}
                stroke={isDark ? "rgba(0,0,0,0.45)" : "rgba(255,255,255,0.7)"}
                strokeWidth={active ? 1.4 : 0.4}
                style={{ cursor: c ? "pointer" : "default" }}
                onMouseEnter={() => setHover(c ?? null)}
              />
            );
          })}
        </svg>

        {/* Tooltip — anchored to the cursor, flips left near the right edge (heatmap idiom). */}
        {hover && (
          <div
            className="pointer-events-none absolute z-10 w-60 rounded-lg border border-border bg-bg/95 p-3 text-xs shadow-lg backdrop-blur"
            style={{
              left: pos.x > pos.w - 250 ? pos.x - 248 : pos.x + 14,
              top: pos.y + 14,
            }}
          >
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold text-fg">{hover.country ?? hover.country_iso}</span>
              <span className="font-mono text-[10px] text-muted">{hover.country_iso}</span>
            </div>
            <div className="mb-1.5 tabular-nums text-muted">
              {hover.active_members.toLocaleString()} active
              {hover.members !== hover.active_members
                ? ` · ${hover.members.toLocaleString()} members`
                : ""}
            </div>
            <table className="w-full tabular-nums">
              <tbody>
                {(["prices", "returns", "fundamentals"] as LayerKey[]).map((l) => (
                  <tr key={l}>
                    <td className="py-0.5 capitalize text-muted">{l}</td>
                    <td className="py-0.5 text-right text-fg">
                      {hover[l].covered}/{hover[l].total}
                    </td>
                    <td className="py-0.5 pl-2 text-right">
                      <Pill s={hover[l].status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hover.timezone && (
              <div className="mt-1.5 text-[11px] text-muted">
                {hover.timezone}
                {hover[layer].latest_date ? ` · latest ${hover[layer].latest_date}` : ""}
              </div>
            )}
          </div>
        )}

        {/* Legend */}
        <div className="absolute bottom-3 left-3 rounded-md border border-border bg-bg/85 px-2.5 py-1.5 text-[11px] backdrop-blur">
          {mode === "population" ? (
            <div className="flex items-center gap-2 text-muted">
              <span>fewer</span>
              <span
                className="h-2 w-24 rounded-full"
                style={{ background: `linear-gradient(90deg, ${mix(popLo, popHi, 0)}, ${mix(popLo, popHi, 1)})` }}
              />
              <span>more members</span>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-emerald-600 dark:text-emerald-400">ok</span>
              <span className="text-amber-600 dark:text-amber-400">partial</span>
              <span className="text-rose-600 dark:text-rose-400">none</span>
              <span className="text-muted">· {layer}</span>
            </div>
          )}
        </div>
      </div>

      <p className="mt-2 text-xs text-muted">
        Countries shaded by{" "}
        {mode === "population" ? (
          <>active member count (log-scaled — the US dwarfs the rest)</>
        ) : (
          <>
            share of <span className="capitalize">{layer}</span> current among active members
          </>
        )}
        . Hover for the per-layer breakdown + market timezone. Delisted names are excluded from
        coverage. Need the names?{" "}
        <Link href={`/sym/explorer${uni ? `?u=${uni}` : ""}`} className="underline">
          open Explorer
        </Link>
        .
      </p>
    </div>
  );
}
