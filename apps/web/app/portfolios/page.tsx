"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type P = Schemas["PortfolioSummary"];

export default function PortfoliosPage() {
  const [list, setList] = useState<P[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [client, setClient] = useState("");

  function load() {
    setLoading(true);
    fetch("/api/portfolios", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: P[]) => {
        setList(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const body: Schemas["CreatePortfolio"] = { name, client, base_currency: "USD" };
    await fetch("/api/portfolios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setName("");
    setClient("");
    load();
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Portfolios</h1>
      <p className="mt-1 text-sm text-muted">
        Clients' portfolios as weights over time. Returns are weighted sym returns (EOD now;
        live once a real-time price source is wired).
      </p>

      <form onSubmit={create} className="mt-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-xs text-muted">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Growth book"
            className="w-56 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg outline-none focus:border-fg/40"
          />
        </div>
        <div>
          <label className="block text-xs text-muted">Client</label>
          <input
            value={client}
            onChange={(e) => setClient(e.target.value)}
            placeholder="optional"
            className="w-40 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg outline-none focus:border-fg/40"
          />
        </div>
        <button
          type="submit"
          className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20"
        >
          + New portfolio
        </button>
      </form>

      <div className="mt-5 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Client</th>
              <th className="px-4 py-2 text-right font-medium">Holdings</th>
              <th className="px-4 py-2 text-right font-medium">As of</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {list.map((p) => (
              <tr key={p.portfolio_id} className="hover:bg-fg/5">
                <td className="px-4 py-2 font-medium">
                  <Link href={`/portfolios/${p.portfolio_id}`} className="hover:underline">
                    {p.name}
                  </Link>
                </td>
                <td className="px-4 py-2 text-muted">{p.client || "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">{p.n_weights}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
                  {p.latest_as_of ?? "—"}
                </td>
              </tr>
            ))}
            {!loading && list.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  No portfolios yet — create one above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
