"use client";

import { useEffect, useMemo, useState } from "react";

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

export default function MacroPage() {
  const [series, setSeries] = useState<SeriesSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<SeriesDetail | null>(null);

  useEffect(() => {
    fetch("/api/macro/series", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: SeriesSummary[]) => {
        setSeries(d);
        if (d[0]) setSel(d[0].series_id);
      })
      .catch(() => setSeries([]));
  }, []);

  useEffect(() => {
    if (!sel) return;
    fetch(`/api/macro/series/${sel}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: SeriesDetail) => setDetail(d))
      .catch(() => setDetail(null));
  }, [sel]);

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">macro</h1>
      <p className="mt-1 text-sm text-muted">
        Central-bank &amp; macroeconomic series from public sources (World Bank, ECB). QRP-managed
        reference data — independent of sym; never fabricated (no-data series are omitted).
      </p>

      <div className="mt-5 grid gap-5 lg:grid-cols-[20rem_1fr]">
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-border">
              {series.map((s) => (
                <tr
                  key={s.series_id}
                  onClick={() => setSel(s.series_id)}
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
              {series.length === 0 && (
                <tr>
                  <td className="px-3 py-6 text-center text-muted">No macro series loaded.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-border bg-surface p-4">
          {detail ? (
            <>
              <div className="flex items-baseline justify-between">
                <div>
                  <div className="font-medium text-fg">
                    {detail.name} — {detail.geo}
                  </div>
                  <div className="text-xs text-muted">
                    {detail.source} · {detail.frequency} · {detail.unit} ·{" "}
                    {detail.observations.length} obs
                  </div>
                </div>
                <div className="text-2xl font-semibold tabular-nums text-fg">
                  {fmt(detail.observations.at(-1)?.value, detail.unit)}
                </div>
              </div>
              <div className="mt-3">
                <LineChart detail={detail} />
              </div>
            </>
          ) : (
            <p className="text-sm text-muted">Select a series.</p>
          )}
        </div>
      </div>
    </div>
  );
}
