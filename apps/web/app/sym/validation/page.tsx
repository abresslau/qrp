import { apiGet } from "@/lib/api";

type Run = {
  run_id: string;
  run_at: string | null;
  universe_id: string | null;
  checks: number | null;
  passed: number | null;
  warned: number | null;
  failed: number | null;
  status: string | null;
};

function statusPill(status: string | null, failed: number | null): string {
  if (failed && failed > 0)
    return "bg-rose-500/10 text-rose-700 ring-rose-600/20 dark:text-rose-400 dark:ring-rose-500/30";
  if (status === "warn")
    return "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-400 dark:ring-amber-500/30";
  return "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-400 dark:ring-emerald-500/30";
}

export default async function ValidationPage() {
  let runs: Run[] = [];
  try {
    runs = await apiGet<Run[]>("/api/sym/validation");
  } catch {
    runs = [];
  }

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Validation</h1>
      <p className="mt-1 text-sm text-muted">Recent <code className="font-mono">validate</code> runs from sym.</p>

      <div className="mt-4 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Run</th>
              <th className="px-4 py-2 font-medium">Universe</th>
              <th className="px-4 py-2 text-right font-medium">Checks</th>
              <th className="px-4 py-2 text-right font-medium">Passed</th>
              <th className="px-4 py-2 text-right font-medium">Warned</th>
              <th className="px-4 py-2 text-right font-medium">Failed</th>
              <th className="px-4 py-2 text-right font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {runs.map((r) => (
              <tr key={r.run_id} className="hover:bg-fg/5">
                <td className="px-4 py-2 tabular-nums text-muted">
                  {r.run_at ? r.run_at.replace("T", " ").slice(0, 16) : "—"}
                </td>
                <td className="px-4 py-2 text-fg">{r.universe_id ?? "all"}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">{r.checks ?? "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                  {r.passed ?? "—"}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-amber-600 dark:text-amber-400">
                  {r.warned ?? "—"}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-rose-600 dark:text-rose-400">
                  {r.failed ?? "—"}
                </td>
                <td className="px-4 py-2 text-right">
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${statusPill(r.status, r.failed)}`}>
                    {r.status ?? "—"}
                  </span>
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  No validation runs (or API unreachable).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-xs text-muted">Live from sym&apos;s validation log.</p>
    </div>
  );
}
