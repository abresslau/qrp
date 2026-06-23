import { DataSnapshotCards } from "@/components/data-snapshot-cards";
import { apiGet } from "@/lib/api";

// Data Monitor › EOD — every data-pipeline bucket's expected-vs-actual business date + (best-effort)
// its latest Dagster run, in one board. Supersedes the old sym Overview (whose warehouse-summary +
// freshness content lives here now). Server-rendered live read; reload to refresh.

type Run = {
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  source: string | null;
} | null;

type Subgroup = { group: string; as_of_date: string; days_behind: number | null };

type BucketRow = {
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
};

type PipelineRun = {
  run_id: string | null;
  mode: string | null;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  rows_written: number | null;
} | null;

type Eod = {
  expected_date: string | null;
  expected_basis: string;
  dagster_runs_available: boolean;
  summary: {
    securities: number | null;
    universes: number | null;
    priced_securities: number | null;
    latest_session: string | null;
    last_pipeline_run: PipelineRun;
  };
  buckets: BucketRow[];
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

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-3 2xl:p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-fg 2xl:text-2xl">{value}</div>
    </div>
  );
}

function ts(s: string | null): string {
  return s ? s.replace("T", " ").slice(0, 19) : "—";
}

export default async function EodMonitorPage() {
  let d: Eod | null = null;
  try {
    d = await apiGet<Eod>("/api/data-monitor/eod");
  } catch {
    d = null;
  }

  if (!d) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">Data Monitor — EOD</h1>
        <p className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">
          API unreachable. Start it: <code className="font-mono">npm run dev</code>
        </p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-fg 2xl:text-2xl">Data Monitor — EOD</h1>
          <p className="mt-1 text-sm text-muted">
            Each pipeline bucket&apos;s latest business date vs expected, and its last run.
          </p>
        </div>
        <div className="text-right text-sm">
          <div className="text-muted">Expected business date</div>
          <div className="font-medium tabular-nums text-fg">{d.expected_date ?? "—"}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:gap-4">
        <Stat label="Securities" value={(d.summary.securities ?? 0).toLocaleString()} />
        <Stat label="Universes" value={d.summary.universes ?? "—"} />
        <Stat label="Priced" value={(d.summary.priced_securities ?? 0).toLocaleString()} />
        <Stat label="Latest session" value={d.summary.latest_session ?? "—"} />
      </div>

      <div className="mt-5">
        <DataSnapshotCards />
      </div>

      <div className="mt-5 overflow-x-auto rounded-xl border border-border">
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
            {d.buckets.map((b) => (
              <tr key={b.key} className="align-top hover:bg-fg/5">
                <td className="px-3 py-2.5">
                  <div className="font-medium text-fg">{b.label}</div>
                  <div className="text-xs text-muted">
                    by {b.subcategory}
                    {b.cadence === "slow" && <span className="ml-1 text-muted/60">· slow-cadence</span>}
                  </div>
                  {(b.coverage || b.note) && (
                    <div className="mt-0.5 text-xs text-muted/70">{b.coverage ?? b.note}</div>
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
                  {b.last_run ? (
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className={`rounded-full px-2 py-0.5 ring-1 ${pill(b.last_run.status ?? "")}`}>
                        {b.last_run.status ?? "—"}
                      </span>
                      <span className="tabular-nums text-muted/70">
                        {ts(b.last_run.finished_at ?? b.last_run.started_at)}
                      </span>
                    </span>
                  ) : (
                    <span className="text-muted/50">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted">
        <span>Expected = {d.expected_basis}.</span>
        <span>
          Dagster runs:{" "}
          {d.dagster_runs_available ? (
            "live"
          ) : (
            <span className="text-muted/70">
              unavailable (start <code className="font-mono">dagster dev -m lineage.definitions</code>)
            </span>
          )}
        </span>
        {d.summary.last_pipeline_run && (
          <span>
            Last sym run: {d.summary.last_pipeline_run.mode ?? "—"} ·{" "}
            {d.summary.last_pipeline_run.status ?? "—"} · {ts(d.summary.last_pipeline_run.started_at)}
          </span>
        )}
      </div>
    </div>
  );
}
