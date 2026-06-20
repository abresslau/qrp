"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";
import { useRunGuard } from "@/lib/use-run-guard";

type P = Schemas["PortfolioSummary"];
type C = Schemas["Client"];

export default function PortfoliosPage() {
  const [list, setList] = useState<P[]>([]);
  const [clients, setClients] = useState<C[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [newClient, setNewClient] = useState("");
  const [filter, setFilter] = useState(""); // "" = all clients (context selection)
  const [createError, setCreateError] = useState<string | null>(null);

  // Guard against concurrent loads (mount / retry / post-create reload can overlap): a run applies
  // its result only if still the latest + still mounted. Without it a slow FAILED mount load
  // resolving after a fast successful retry would clobber the just-loaded rows with a stale error.
  const guard = useRunGuard();

  // Pure fetch: state is only set in the async callbacks, never synchronously — so the mount
  // effect can call it without tripping react-hooks/set-state-in-effect (loading starts true).
  // useCallback so the mount effect can depend on it (guard is stable → fetchData is stable).
  const fetchData = useCallback(() => {
    const isCurrent = guard.begin();
    Promise.all([
      fetch("/api/portfolios", { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`portfolios ${r.status}`); // an HTTP error is a load failure, not a list
        return r.json();
      }),
      fetch("/api/portfolios/clients", { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`clients ${r.status}`);
        return r.json();
      }),
    ])
      .then(([p, c]: [P[], C[]]) => {
        if (!isCurrent()) return; // a newer load has superseded this one (or we unmounted)
        setList(p);
        setClients(c);
        setError(false);
        setLoading(false);
      })
      // QH.8: surface a load failure honestly (an empty list must not look like a real failure).
      .catch(() => {
        if (!isCurrent()) return; // don't let a stale failure clobber a newer success
        setError(true);
        setLoading(false);
      });
  }, [guard]);
  // For event-handler refreshes (e.g. after create / retry) we DO want the immediate loading flip.
  function load() {
    setLoading(true);
    setError(false);
    fetchData();
  }
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Create helpers check r.ok and catch network errors — a failed POST must surface an error, not
  // silently clear the form + reload (which looks like success) or escape as an unhandled rejection.
  async function postJson(url: string, body: unknown): Promise<string | null> {
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) return null;
      const res: { error?: { message?: string } } = await r.json().catch(() => ({}));
      return res.error?.message ?? `request failed (${r.status})`;
    } catch {
      return "request failed — check your connection and retry";
    }
  }

  async function createPortfolio(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreateError(null);
    const body: Schemas["CreatePortfolio"] = { name, client, base_currency: "USD" };
    const err = await postJson("/api/portfolios", body);
    if (err) {
      setCreateError(`Couldn't create portfolio: ${err}`);
      return; // keep the form populated so the user can retry
    }
    setName("");
    setClient("");
    load();
  }

  async function createClient(e: React.FormEvent) {
    e.preventDefault();
    if (!newClient.trim()) return;
    setCreateError(null);
    const body: Schemas["CreateClient"] = { name: newClient };
    const err = await postJson("/api/portfolios/clients", body);
    if (err) {
      setCreateError(`Couldn't create client: ${err}`);
      return;
    }
    setNewClient("");
    load();
  }

  const shown = filter ? list.filter((p) => p.client === filter) : list;

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Portfolios</h1>
      <p className="mt-1 text-sm text-muted">
        Clients&apos; portfolios as weights over time. Returns are weighted sym returns (EOD now;
        live once a real-time price source is wired).
      </p>

      {/* Clients (FR-13): manage clients + select a Client->Portfolio context */}
      <div className="mt-4 rounded-xl border border-border bg-surface p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-muted">Clients</span>
          <button
            onClick={() => setFilter("")}
            className={`rounded-full border px-3 py-1 text-xs ${
              filter === ""
                ? "border-fg/40 bg-fg/10 text-fg"
                : "border-border text-muted hover:text-fg"
            }`}
          >
            All ({list.length})
          </button>
          {clients.map((c) => (
            <button
              key={c.client_id}
              onClick={() => setFilter(c.name)}
              className={`rounded-full border px-3 py-1 text-xs ${
                filter === c.name
                  ? "border-fg/40 bg-fg/10 text-fg"
                  : "border-border text-muted hover:text-fg"
              }`}
            >
              {c.name} ({c.n_portfolios})
            </button>
          ))}
          <form onSubmit={createClient} className="ml-auto flex items-center gap-2">
            <input
              value={newClient}
              onChange={(e) => setNewClient(e.target.value)}
              placeholder="New client"
              className="w-36 rounded-md border border-border bg-bg px-2 py-1 text-xs text-fg outline-none focus:border-fg/40"
            />
            <button
              type="submit"
              className="rounded-md border border-border bg-fg/10 px-2 py-1 text-xs font-medium text-fg hover:bg-fg/20"
            >
              + Client
            </button>
          </form>
        </div>
      </div>

      <form onSubmit={createPortfolio} className="mt-4 flex flex-wrap items-end gap-2">
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
            placeholder="pick or type"
            list="client-options"
            className="w-40 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg outline-none focus:border-fg/40"
          />
          <datalist id="client-options">
            {clients.map((c) => (
              <option key={c.client_id} value={c.name} />
            ))}
          </datalist>
        </div>
        <button
          type="submit"
          className="rounded-md border border-border bg-fg/10 px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg/20"
        >
          + New portfolio
        </button>
      </form>
      {createError && (
        <p role="alert" className="mt-2 text-sm text-red-500">
          {createError}
        </p>
      )}

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
            {shown.map((p) => (
              <tr key={p.portfolio_id} className="hover:bg-fg/5">
                <td className="px-4 py-2 font-medium">
                  <Link href={`/portfolios/${p.portfolio_id}`} className="hover:underline">
                    {p.name}
                  </Link>
                </td>
                <td className="px-4 py-2 text-muted">{p.client || "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
                  {p.n_holdings}
                  {p.n_snapshots > 1 ? (
                    <span className="text-[11px] opacity-70"> · {p.n_snapshots} snapshots</span>
                  ) : null}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-muted">
                  {p.latest_as_of_date ?? "—"}
                </td>
              </tr>
            ))}
            {!loading && error && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  Couldn&apos;t load portfolios.{" "}
                  <button
                    type="button"
                    onClick={load}
                    className="font-medium text-fg underline hover:no-underline"
                  >
                    Retry
                  </button>
                </td>
              </tr>
            )}
            {!loading && !error && shown.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  {filter
                    ? `No portfolios for ${filter}.`
                    : "No portfolios yet — create one above."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
