"use client";

import { useEffect, useMemo, useState } from "react";

import type { Schemas } from "@/lib/api";

type AltSeries = Schemas["AltSeries"];
type AltSeriesDetail = Schemas["AltSeriesDetail"];

const SOURCE_LABEL: Record<string, string> = {
  wikipedia: "Wikipedia",
  sec_edgar: "SEC EDGAR",
};

function seriesKey(s: { composite_figi: string; source: string; metric: string }) {
  return `${s.composite_figi}|${s.source}|${s.metric}`;
}

function metricLabel(metric: string) {
  return metric.replace(/_/g, " ");
}

function Spark({ detail }: { detail: AltSeriesDetail }) {
  const path = useMemo(() => {
    const pts = detail.observations;
    if (pts.length < 2) return "";
    const W = 720;
    const H = 200;
    const PAD = 24;
    const ys = pts.map((p) => p.value);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanY = maxY - minY || 1;
    const sx = (i: number) => PAD + (i / (pts.length - 1)) * (W - 2 * PAD);
    const sy = (v: number) => H - PAD - ((v - minY) / spanY) * (H - 2 * PAD);
    return pts.map((p, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
  }, [detail]);
  if (detail.observations.length === 0) return <p className="text-sm text-muted">No data.</p>;
  if (detail.observations.length === 1) {
    const only = detail.observations[0];
    return (
      <p className="text-sm text-muted">
        Single observation: {only.value.toLocaleString()} on {only.obs_date}.
      </p>
    );
  }
  return (
    <svg viewBox="0 0 720 200" className="w-full">
      <path d={path} fill="none" stroke="currentColor" strokeWidth={1.8} className="text-sky-500" />
    </svg>
  );
}

export default function AltdataPage() {
  const [series, setSeries] = useState<AltSeries[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<AltSeriesDetail | null>(null);

  useEffect(() => {
    fetch("/api/altdata/series", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: AltSeries[]) => {
        setSeries(d);
        if (d[0]) setSel(seriesKey(d[0]));
      })
      .catch(() => setSeries([]));
  }, []);

  useEffect(() => {
    if (!sel) return;
    const [figi, source, metric] = sel.split("|");
    const qs = new URLSearchParams({ source, metric });
    fetch(`/api/altdata/series/${figi}?${qs}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d: AltSeriesDetail) => setDetail(d))
      .catch(() => setDetail(null));
  }, [sel]);

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">alt data</h1>
      <p className="mt-1 text-sm text-muted">
        Alternative-data series, mapped to sym securities. Sources: Wikimedia daily pageviews
        (attention proxy) and SEC EDGAR filing activity (Form 4 insider transactions, 8-K corporate
        events — daily counts; days without filings are true zeros, not stored). Spike = 7-day rate
        ÷ 30-day rate (&gt;1 = rising activity). QRP-managed; live external data, never fabricated.
      </p>

      <div className="mt-5 grid gap-5 lg:grid-cols-[26rem_1fr]">
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Company</th>
                <th className="px-3 py-2 font-medium">Series</th>
                <th className="px-3 py-2 text-right font-medium">Latest</th>
                <th className="px-3 py-2 text-right font-medium">Spike</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {series.map((s) => {
                const key = seriesKey(s);
                const sp = s.attention_spike;
                const cls =
                  sp == null
                    ? "text-muted"
                    : sp >= 1.02
                      ? "text-emerald-600 dark:text-emerald-400"
                      : sp <= 0.98
                        ? "text-rose-600 dark:text-rose-400"
                        : "text-muted";
                return (
                  <tr
                    key={key}
                    onClick={() => setSel(key)}
                    className={`cursor-pointer ${sel === key ? "bg-fg/10" : "hover:bg-fg/5"}`}
                  >
                    <td className="px-3 py-2">
                      <span className="font-medium text-fg">{s.ticker}</span>{" "}
                      <span className="text-muted">{s.name}</span>
                    </td>
                    <td className="px-3 py-2 text-muted">
                      {SOURCE_LABEL[s.source] ?? s.source} · {metricLabel(s.metric)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-fg">
                      {s.latest_value?.toLocaleString() ?? "—"}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums ${cls}`}>
                      {sp == null ? "—" : `${sp.toFixed(2)}×`}
                    </td>
                  </tr>
                );
              })}
              {series.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-muted">
                    No alt-data series loaded.
                  </td>
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
                    {detail.name} ({detail.ticker})
                  </div>
                  <div className="text-xs text-muted">
                    {SOURCE_LABEL[detail.source] ?? detail.source}: {metricLabel(detail.metric)}
                    {detail.detail ? ` · ${detail.detail}` : ""} · {detail.observations.length}
                    {detail.source === "sec_edgar" ? " filing days" : " days"}
                  </div>
                </div>
                <div className="text-2xl font-semibold tabular-nums text-fg">
                  {detail.observations.at(-1)?.value.toLocaleString()}
                </div>
              </div>
              <div className="mt-3">
                <Spark detail={detail} />
              </div>
              <p className="mt-1 text-xs text-muted">
                daily {detail.unit ?? "values"} · {SOURCE_LABEL[detail.source] ?? detail.source}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">Select a series.</p>
          )}
        </div>
      </div>
    </div>
  );
}
