import Link from "next/link";
import { apiGet } from "@/lib/api";

type Layer = { covered: number; total: number; latest_date: string | null; status: string };
type Cov = {
  universe_id: string;
  name: string | null;
  members_resolved: number;
  active_members: number;
  prices: Layer;
  returns: Layer;
  fundamentals: Layer;
};

function pill(status: string): string {
  if (status === "ok")
    return "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-400 dark:ring-emerald-500/30";
  if (status === "partial")
    return "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-400 dark:ring-amber-500/30";
  return "bg-rose-500/10 text-rose-700 ring-rose-600/20 dark:text-rose-400 dark:ring-rose-500/30"; // missing
}

function LayerCell({ layer, universeId, layerKey }: { layer: Layer; universeId: string; layerKey: string }) {
  const badge = (
    <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ${pill(layer.status)}`}>
      {layer.status}
    </span>
  );
  return (
    <td className="px-4 py-2 text-right">
      <div className="flex items-center justify-end gap-2">
        <span className="tabular-nums text-fg">
          {layer.covered}/{layer.total}
        </span>
        {layer.status === "ok" ? (
          badge
        ) : (
          // partial/missing → drill into the gap names on Explorer
          <Link href={`/sym/explorer?u=${universeId}&gap=${layerKey}`} title="Show the missing names" className="hover:opacity-80">
            {badge}
          </Link>
        )}
      </div>
      <div className="text-[11px] tabular-nums text-muted">{layer.latest_date ?? "—"}</div>
    </td>
  );
}

export default async function UniversesPage() {
  let rows: Cov[] = [];
  try {
    rows = await apiGet<Cov[]>("/api/sym/universes/coverage");
  } catch {
    rows = [];
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Universes</h1>
      <p className="mt-1 text-sm text-muted">
        Coverage per universe — Prices, Returns, Fundamentals. Coverage is judged per-member
        (markets close at different times) over <strong>active</strong> members — delisted names
        aren&apos;t expected to have current data, so they don&apos;t count against coverage.
      </p>

      <div className="mt-4 overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Universe</th>
              <th className="px-4 py-2 text-right font-medium">Members</th>
              <th className="px-4 py-2 text-right font-medium">Active</th>
              <th className="px-4 py-2 text-right font-medium">Prices</th>
              <th className="px-4 py-2 text-right font-medium">Returns</th>
              <th className="px-4 py-2 text-right font-medium">Fundamentals</th>
              <th className="px-4 py-2 text-right font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((u) => (
              <tr key={u.universe_id} className="hover:bg-fg/5">
                <td className="px-4 py-2 text-fg">
                  <Link href={`/sym/explorer?u=${u.universe_id}`} className="font-medium hover:underline">
                    {u.name ?? u.universe_id}
                  </Link>
                  <span className="ml-2 font-mono text-[11px] text-muted">{u.universe_id}</span>
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
                  {u.members_resolved.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-fg">
                  {u.active_members.toLocaleString()}
                  {u.members_resolved !== u.active_members && (
                    <span
                      className="ml-1 text-[11px] text-muted"
                      title={`${u.members_resolved - u.active_members} delisted (excluded from coverage)`}
                    >
                      −{u.members_resolved - u.active_members}
                    </span>
                  )}
                </td>
                <LayerCell layer={u.prices} universeId={u.universe_id} layerKey="prices" />
                <LayerCell layer={u.returns} universeId={u.universe_id} layerKey="returns" />
                <LayerCell layer={u.fundamentals} universeId={u.universe_id} layerKey="fundamentals" />
                <td className="px-4 py-2 text-right">
                  <Link
                    href={`/sym/heatmap?u=${u.universe_id}`}
                    className="text-emerald-600 hover:underline dark:text-emerald-400"
                  >
                    Heat map →
                  </Link>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  No universe coverage (API unreachable, or no resolved members).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-muted">
        <span className="text-emerald-600 dark:text-emerald-400">ok</span> = all members current ·{" "}
        <span className="text-amber-600 dark:text-amber-400">partial</span> = some members lag/missing ·{" "}
        <span className="text-rose-600 dark:text-rose-400">missing</span> = none. Fundamentals are
        low-cadence (reported ~quarterly), so a recent-enough figure counts as covered. Warehouse
        health + per-area freshness is on <Link href="/sym/overview" className="underline">Overview</Link>.
      </p>
    </div>
  );
}
