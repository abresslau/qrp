import Link from "next/link";
import { apiGet } from "@/lib/api";

type U = { universe_id: string; name: string; members_resolved: number };

export default async function UniversesPage() {
  let us: U[] = [];
  try {
    us = await apiGet<U[]>("/api/sym/universes");
  } catch {
    us = [];
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Universes</h1>
      <p className="mt-1 text-sm text-muted">Registered index universes and resolved membership.</p>

      <div className="mt-4 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Universe</th>
              <th className="px-4 py-2 font-mono font-medium">id</th>
              <th className="px-4 py-2 text-right font-medium">Resolved members</th>
              <th className="px-4 py-2 text-right font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {us.map((u) => (
              <tr key={u.universe_id} className="hover:bg-fg/5">
                <td className="px-4 py-2 text-fg">{u.name}</td>
                <td className="px-4 py-2 font-mono text-xs text-muted">{u.universe_id}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
                  {u.members_resolved.toLocaleString()}
                </td>
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
            {us.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  No universes (or API unreachable).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-xs text-muted">Live from sym — every figure ties to the warehouse.</p>
    </div>
  );
}
