"use client";

import { useEffect, useMemo, useState } from "react";

import { COMPARISON_CATEGORIES, MacroCompare } from "@/components/macro-compare";
import type { Schemas } from "@/lib/api";

type SeriesSummary = Schemas["SeriesSummary"];
type SeriesDetail = Schemas["SeriesDetail"];

function fmt(v: number | null | undefined, unit?: string | null): string {
  if (v == null) return "—";
  return `${v.toFixed(2)}${unit?.includes("%") ? "%" : ""}`;
}

function LineChart({ detail }: { detail: SeriesDetail }) {
  const pts = detail.observations;
  const { path, area, lo, hi, x0, x1 } = useMemo(() => {
    if (pts.length < 2) return { path: "", area: "", lo: 0, hi: 0, x0: "", x1: "" };
    const W = 720;
    const H = 240;
    const PAD = 28;
    const xs = pts.map((p) => new Date(p.obs_date).getTime());
    const ys = pts.map((p) => p.value);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const sx = (t: number) => PAD + ((t - minX) / spanX) * (W - 2 * PAD);
    const sy = (v: number) => H - PAD - ((v - minY) / spanY) * (H - 2 * PAD);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(xs[i]).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
    const a = `${d} L${sx(maxX).toFixed(1)},${H - PAD} L${sx(minX).toFixed(1)},${H - PAD} Z`;
    return {
      path: d,
      area: a,
      lo: minY,
      hi: maxY,
      x0: new Date(minX).getFullYear().toString(),
      x1: new Date(maxX).getFullYear().toString(),
    };
  }, [pts]);

  if (pts.length < 2) return <p className="text-sm text-muted">Not enough observations to chart.</p>;
  return (
    <div>
      <svg viewBox="0 0 720 240" className="w-full">
        <path d={area} fill="currentColor" className="text-sky-500/10" />
        <path d={path} fill="none" stroke="currentColor" strokeWidth={1.8} className="text-sky-500" />
      </svg>
      <div className="flex justify-between text-xs text-muted">
        <span>{x0}</span>
        <span>
          range {fmt(lo, detail.unit)} – {fmt(hi, detail.unit)}
        </span>
        <span>{x1}</span>
      </div>
    </div>
  );
}

/** The macro series browser. `category` (a sidebar submenu slug) filters the list;
 *  undefined = all series. An unknown category yields an honest empty state. */
export function MacroBrowser({ category }: { category?: string }) {
  const [series, setSeries] = useState<SeriesSummary[]>([]);
  // loading/error/ready are distinct states: a fetch failure must never render as the
  // data fact "no series in this category", and the load gap must not flash it either.
  const [seriesState, setSeriesState] = useState<"loading" | "error" | "ready">("loading");
  const [clicked, setClicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<SeriesDetail | null>(null);
  // the SELECTION the failure belongs to — a stale failure must not label the next pick
  const [errorFor, setErrorFor] = useState<string | null>(null);

  useEffect(() => {
    // re-runs on category navigation too: a cold-start failure must not stick as
    // "API unreachable" across every sibling category (the refetch is one cheap call)
    fetch("/api/macro/series", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: SeriesSummary[]) => {
        setSeries(d);
        setSeriesState("ready");
      })
      .catch(() => {
        setSeries([]);
        setSeriesState("error");
      });
  }, [category]);

  const visible = useMemo(
    () => (category ? series.filter((s) => s.category === category) : series),
    [series, category]
  );

  // Selection is DERIVED: the clicked series while it's visible, else the first visible
  // one (no state-syncing effect — a click that filtering removed falls back honestly).
  const sel =
    clicked && visible.some((s) => s.series_id === clicked)
      ? clicked
      : (visible[0]?.series_id ?? null);

  useEffect(() => {
    if (!sel) return;
    // Out-of-order guard: click A then B — A's late response must not overwrite B's
    // detail (the `shown` staleness check would then blank the pane with no refetch).
    let stale = false;
    fetch(`/api/macro/series/${sel}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: SeriesDetail) => {
        if (stale) return;
        setDetail(d);
        setErrorFor(null);
      })
      .catch(() => {
        if (stale) return;
        setDetail(null);
        setErrorFor(sel);
      });
    return () => {
      stale = true;
    };
  }, [sel]);

  // Show the detail only when it matches the current selection — a stale chart never
  // renders against an empty or re-filtered list.
  const shown = detail && detail.series_id === sel ? detail : null;

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">
        macro{category ? <span className="text-muted"> · {category}</span> : null}
      </h1>
      <p className="mt-1 text-sm text-muted">
        Central-bank &amp; macroeconomic series from public sources (World Bank, ECB, US Treasury,
        OECD, Eurostat). QRP-managed reference data — independent of sym; never fabricated
        (no-data series are omitted).
      </p>

      {category && COMPARISON_CATEGORIES.includes(category) && seriesState === "ready" && (
        // keyed by category: a switch remounts the comparison, so no cross-category races
        <div className="mt-5">
          <MacroCompare key={category} category={category} series={visible} />
        </div>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[20rem_1fr]">
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-border">
              {visible.map((s) => (
                <tr
                  key={s.series_id}
                  onClick={() => setClicked(s.series_id)}
                  className={`cursor-pointer ${sel === s.series_id ? "bg-fg/10" : "hover:bg-fg/5"}`}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-fg">{s.name}</div>
                    <div className="text-xs text-muted">
                      {s.geo} · {s.source} · {s.frequency}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-fg">
                    {fmt(s.latest, s.unit)}
                  </td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td className="px-3 py-6 text-center text-muted">
                    {seriesState === "loading"
                      ? "Loading series…"
                      : seriesState === "error"
                        ? "Couldn’t load series (API unreachable)."
                        : category
                          ? `No series in category “${category}”.`
                          : "No macro series loaded."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          {shown ? (
            <>
              <div className="flex items-baseline justify-between">
                <div>
                  <div className="font-medium text-fg">
                    {shown.name} — {shown.geo}
                  </div>
                  <div className="text-xs text-muted">
                    {shown.source} · {shown.frequency} · {shown.unit} ·{" "}
                    {shown.observations.length} obs
                  </div>
                </div>
                <div className="text-2xl font-semibold tabular-nums text-fg">
                  {fmt(shown.observations.at(-1)?.value, shown.unit)}
                </div>
              </div>
              <div className="mt-3">
                <LineChart detail={shown} />
              </div>
            </>
          ) : sel && errorFor === sel ? (
            <p className="text-sm text-muted">Couldn’t load series detail.</p>
          ) : sel ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : (
            <p className="text-sm text-muted">Select a series.</p>
          )}
        </div>
      </div>
    </div>
  );
}
