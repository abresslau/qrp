import { type BucketRow, EodTable } from "@/components/eod-table";
import { apiGet } from "@/lib/api";

// Data Monitor — every data-pipeline bucket's expected-vs-actual business date, its instrument count,
// and (best-effort) its latest Dagster run, in one board with an expandable per-subcategory breakdown
// (equity by universe, rates by country, index levels by index, universe membership by universe).
// Single tab-less screen; server-rendered live read; reload to refresh.

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

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 2xl:rounded-xl 2xl:p-3">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums text-fg 2xl:text-xl">{value}</div>
    </div>
  );
}

function ts(s: string | null): string {
  return s ? s.replace("T", " ").slice(0, 19) : "—";
}

export default async function DataMonitorPage() {
  let d: Eod | null = null;
  try {
    d = await apiGet<Eod>("/api/data-monitor/eod");
  } catch {
    d = null;
  }

  if (!d) {
    return (
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-fg">Data Monitor</h1>
        <p className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">
          API unreachable. Start it: <code className="font-mono">npm run dev</code>
        </p>
      </div>
    );
  }

  // asset-class instrument counts for the summary cards — reuse the per-bucket counts already on the
  // board (single source of truth; no extra query). null → "—".
  const countByKey = new Map(d.buckets.map((b) => [b.key, b.instrument_count]));
  const fmtCount = (k: string) => countByKey.get(k)?.toLocaleString() ?? "—";

  return (
    <div className="w-full">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-fg 2xl:text-xl">Data Monitor</h1>
          <p className="text-sm text-muted">
            Each pipeline bucket&apos;s latest business date vs expected, its coverage, and last run.
          </p>
        </div>
        <div className="text-right text-sm">
          <div className="text-muted">Expected business date</div>
          <div className="font-medium tabular-nums text-fg">{d.expected_date ?? "—"}</div>
        </div>
      </div>

      {/* one card per asset class — equities (securities) + universes from the warehouse summary,
          FX / rates / commodities from their bucket instrument counts. */}
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6 2xl:gap-3">
        <Stat label="Securities" value={(d.summary.securities ?? 0).toLocaleString()} />
        <Stat label="Universes" value={d.summary.universes ?? "—"} />
        <Stat label="Indices" value={fmtCount("index_levels")} />
        <Stat label="FX pairs" value={fmtCount("fx")} />
        <Stat label="Rates curves" value={fmtCount("rates")} />
        <Stat label="Commodities" value={fmtCount("commodities")} />
      </div>

      <div className="mt-3">
        <EodTable buckets={d.buckets} />
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
