import { apiGet } from "@/lib/api";

type Freshness = {
  area: string;
  as_of_date: string | null;
  days_behind: number | null;
  status: "ok" | "stale" | "unknown";
  coverage: string | null;
};
type LastRun = {
  run_id: string;
  mode: string | null;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  rows_written: number | null;
} | null;
type Overview = {
  securities: number;
  universes: number;
  priced_securities: number;
  priced_at_latest: number;
  latest_session: string | null;
  freshness: Freshness[];
  last_run: LastRun;
};

function pill(status: string): string {
  if (status === "ok" || status === "success")
    return "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-400 dark:ring-emerald-500/30";
  if (status === "stale" || status === "partial")
    return "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-400 dark:ring-amber-500/30";
  return "bg-fg/5 text-muted ring-border";
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-fg">{value}</div>
    </div>
  );
}

export default async function SymOverviewPage() {
  let o: Overview | null = null;
  try {
    o = await apiGet<Overview>("/api/sym/overview");
  } catch {
    o = null;
  }

  if (!o) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">sym — Overview</h1>
        <p className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">
          API unreachable. Start it: <code className="font-mono">uv run uvicorn qrp_api.main:app --port 8000</code>
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">sym — Overview</h1>
          <p className="mt-1 text-sm text-muted">Warehouse health at a glance.</p>
        </div>
        <div className="text-right text-sm">
          <div className="text-muted">Latest session</div>
          <div className="font-medium tabular-nums text-fg">{o.latest_session ?? "—"}</div>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Securities" value={o.securities.toLocaleString()} />
        <Stat label="Universes" value={o.universes} />
        <Stat label="Priced" value={o.priced_securities.toLocaleString()} />
        <Stat
          label="At latest session"
          value={
            <>
              {o.priced_at_latest.toLocaleString()}
              <span className="ml-1 text-sm font-normal text-muted">/ {o.priced_securities.toLocaleString()}</span>
            </>
          }
        />
      </div>

      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">Freshness</h2>
      <div className="mt-3 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <tbody className="divide-y divide-border">
            {o.freshness.map((f) => (
              <tr key={f.area} className="hover:bg-fg/5">
                <td className="px-4 py-3 capitalize text-fg">
                  {f.area}
                  {f.coverage && <span className="ml-2 text-xs text-muted/70">{f.coverage}</span>}
                </td>
                <td className="px-4 py-3 tabular-nums text-muted">{f.as_of_date ?? "—"}</td>
                <td className="px-4 py-3 tabular-nums text-muted">
                  {f.days_behind === null ? "" : `${f.days_behind}d behind`}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${pill(f.status)}`}>
                    {f.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">Last run</h2>
      <div className="mt-3 rounded-xl border border-border bg-surface p-4 text-sm">
        {o.last_run ? (
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
            <div>
              <span className="text-muted">Mode</span>{" "}
              <span className="font-medium text-fg">{o.last_run.mode ?? "—"}</span>
            </div>
            <div>
              <span className="text-muted">Status</span>{" "}
              <span className={`ml-1 rounded-full px-2 py-0.5 text-xs ring-1 ${pill(o.last_run.status ?? "")}`}>
                {o.last_run.status ?? "—"}
              </span>
            </div>
            <div className="tabular-nums text-muted">
              {o.last_run.started_at ? o.last_run.started_at.replace("T", " ").slice(0, 19) : "—"}
            </div>
            <div className="tabular-nums text-muted">
              {o.last_run.rows_written != null
                ? `${o.last_run.rows_written.toLocaleString()} rows`
                : ""}
            </div>
          </div>
        ) : (
          <div className="text-muted">No runs recorded.</div>
        )}
      </div>

      <p className="mt-8 text-xs text-muted">
        All figures are live reads of sym — every number ties to the warehouse.
      </p>
    </div>
  );
}
