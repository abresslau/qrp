"use client";

import { useState } from "react";

// The EOD freshness table with collapsible per-subcategory breakdown rows: rates → country,
// equity_prices → universe, index_levels → index, universe → universe (member counts). A bucket
// with subgroups is expandable (click the row); the breakdown rows show each subcategory's actual
// date + how far behind it is. Server page fetches; this only renders + handles expand/collapse.

export type Subgroup = { group: string; as_of_date: string | null; days_behind: number | null; detail: string | null };
type Run = { status: string | null; started_at: string | null; finished_at: string | null; source: string | null } | null;

export type BucketRow = {
  key: string;
  label: string;
  subcategory: string;
  datasets: string[];
  cadence: string;
  note: string | null;
  actual_date: string | null;
  expected_date: string | null;
  days_behind: number | null;
  status: "ok" | "stale" | "unknown";
  coverage: string | null;
  error: string | null;
  subgroups: Subgroup[];
  last_run: Run;
  dagster_url: string | null;
};

function pill(status: string): string {
  if (status === "ok" || status === "SUCCESS" || status === "success")
    return "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-400 dark:ring-emerald-500/30";
  if (status === "stale" || status === "STARTED" || status === "partial")
    return "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-400 dark:ring-amber-500/30";
  if (status === "FAILURE" || status === "CANCELED" || status === "failed")
    return "bg-red-500/10 text-red-700 ring-red-600/20 dark:text-red-400 dark:ring-red-500/30";
  return "bg-fg/5 text-muted ring-border";
}

function ts(s: string | null): string {
  return s ? s.replace("T", " ").slice(0, 19) : "—";
}

// Per-subgroup verdict from days behind: null → neutral (event-log), 0 → ok, >0 → stale.
function subStatus(d: number | null): "ok" | "stale" | null {
  return d == null ? null : d > 0 ? "stale" : "ok";
}

const isStaleSub = (s: Subgroup) => s.days_behind != null && s.days_behind > 0;
const bucketIsStale = (b: BucketRow) => b.status === "stale" || b.subgroups.some(isStaleSub);

export function EodTable({ buckets }: { buckets: BucketRow[] }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [staleOnly, setStaleOnly] = useState(false);

  const staleCount = buckets.filter(bucketIsStale).length;
  const shown = staleOnly ? buckets.filter(bucketIsStale) : buckets;

  return (
    <div>
      <div className="mb-2 flex items-center justify-end gap-3">
        {staleOnly && (
          <span className="text-xs text-muted">{shown.length} of {buckets.length} buckets behind</span>
        )}
        <button
          type="button"
          onClick={() => setStaleOnly((v) => !v)}
          aria-pressed={staleOnly}
          className={`rounded-md px-2.5 py-1 text-xs font-medium ring-1 transition ${
            staleOnly
              ? "bg-amber-500/15 text-amber-700 ring-amber-600/30 dark:text-amber-300"
              : "text-muted ring-border hover:text-fg hover:bg-fg/5"
          }`}
        >
          {staleOnly ? "Showing stale only" : "Stale only"} ({staleCount})
        </button>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Bucket</th>
              <th className="px-3 py-2 font-medium">Dataset</th>
              <th className="px-3 py-2 text-right font-medium">Expected</th>
              <th className="px-3 py-2 text-right font-medium">Actual</th>
              <th className="px-3 py-2 text-right font-medium">Behind</th>
              <th className="px-3 py-2 text-center font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Last run</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {shown.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-sm text-muted">
                  Nothing stale — every bucket is current. 🎉
                </td>
              </tr>
            )}
            {shown.map((b) => {
              // When filtering, show only the stale subgroups and force the breakdown open.
              const subs = staleOnly ? b.subgroups.filter(isStaleSub) : b.subgroups;
              const expanded = staleOnly ? subs.length > 0 : !!open[b.key];
              const toggleable = !staleOnly && b.subgroups.length > 0;
              return (
                <BucketRows
                  key={b.key}
                  b={b}
                  subs={subs}
                  expanded={expanded}
                  toggleable={toggleable}
                  onToggle={() => toggleable && setOpen((o) => ({ ...o, [b.key]: !o[b.key] }))}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BucketRows({ b, subs, expanded, toggleable, onToggle }: {
  b: BucketRow; subs: Subgroup[]; expanded: boolean; toggleable: boolean; onToggle: () => void;
}) {
  const hasSub = b.subgroups.length > 0;
  return (
    <>
      <tr
        className={`align-top ${toggleable ? "cursor-pointer" : ""} hover:bg-fg/5`}
        onClick={onToggle}
      >
        <td className="px-3 py-2.5">
          <div className="flex items-center gap-1.5 font-medium text-fg">
            {hasSub && (
              <span
                className={`text-muted transition-transform ${expanded ? "rotate-90" : ""} ${toggleable ? "" : "opacity-40"}`}
                aria-hidden
              >
                ▸
              </span>
            )}
            {b.label}
            {hasSub && <span className="text-xs font-normal text-muted/60">({b.subgroups.length})</span>}
          </div>
          <div className="pl-[1.1rem] text-xs text-muted">
            by {b.subcategory}
            {b.cadence === "slow" && <span className="ml-1 text-muted/60">· slow-cadence</span>}
          </div>
          {(b.coverage || b.note) && (
            <div className="pl-[1.1rem] mt-0.5 text-xs text-muted/70">{b.coverage ?? b.note}</div>
          )}
        </td>
        <td className="px-3 py-2.5 font-mono text-xs text-muted">{b.datasets.join(", ")}</td>
        <td className="px-3 py-2.5 text-right tabular-nums text-muted">{b.expected_date ?? "—"}</td>
        <td className="px-3 py-2.5 text-right tabular-nums text-fg">{b.actual_date ?? "—"}</td>
        <td className="px-3 py-2.5 text-right tabular-nums text-muted">
          {b.days_behind === null ? "—" : `${b.days_behind}d`}
        </td>
        <td className="px-3 py-2.5 text-center">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${pill(b.status)}`}>
            {b.error ? "unknown" : b.status}
          </span>
        </td>
        <td className="px-3 py-2.5 text-xs">
          <span className="flex flex-wrap items-center gap-1.5">
            {b.last_run ? (
              <>
                <span className={`rounded-full px-2 py-0.5 ring-1 ${pill(b.last_run.status ?? "")}`}>
                  {b.last_run.status ?? "—"}
                </span>
                <span className="tabular-nums text-muted/70">{ts(b.last_run.finished_at ?? b.last_run.started_at)}</span>
              </>
            ) : (
              <span className="text-muted/50">no run</span>
            )}
            {b.dagster_url && (
              <a
                href={b.dagster_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                title="Open this job in Dagster"
                className="text-muted underline-offset-2 hover:text-fg hover:underline"
              >
                Dagster ↗
              </a>
            )}
          </span>
        </td>
      </tr>
      {expanded &&
        subs.map((s) => {
          const st = subStatus(s.days_behind);
          return (
            <tr key={`${b.key}:${s.group}`} className="bg-fg/[0.02] text-xs">
              <td className="py-1.5 pl-9 pr-3">
                <span className="text-fg/90">{s.group}</span>
                {s.detail && <span className="ml-2 text-muted/60">{s.detail}</span>}
              </td>
              <td />
              <td />
              <td className="px-3 py-1.5 text-right tabular-nums text-muted">{s.as_of_date ?? "—"}</td>
              <td className="px-3 py-1.5 text-right tabular-nums text-muted">
                {s.days_behind === null ? "—" : `${s.days_behind}d`}
              </td>
              <td className="px-3 py-1.5 text-center">
                {st && (
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${pill(st)}`}>{st}</span>
                )}
              </td>
              <td />
            </tr>
          );
        })}
    </>
  );
}
