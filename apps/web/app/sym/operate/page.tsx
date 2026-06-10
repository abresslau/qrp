"use client";

import { Fragment, useCallback, useEffect, useState } from "react";

import type { Schemas } from "@/lib/api";

type OpDef = Schemas["OpDef"];
type Job = Schemas["Job"];
type RunResult = Schemas["RunResult"];
type UniverseRef = { universe_id: string; name: string };

const STATUS_STYLE: Record<string, string> = {
  queued: "text-muted",
  running: "text-sky-600 dark:text-sky-400",
  success: "text-emerald-600 dark:text-emerald-400",
  failed: "text-rose-600 dark:text-rose-400",
  rejected: "text-amber-600 dark:text-amber-400",
};

export default function OperatePage() {
  const [ops, setOps] = useState<OpDef[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [universes, setUniverses] = useState<UniverseRef[]>([]);
  const [universe, setUniverse] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const loadJobs = useCallback(() => {
    fetch("/api/operate/jobs?limit=25", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Job[]) => setJobs(d))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch("/api/operate/ops", { cache: "no-store" }).then((r) => r.json()).then(setOps).catch(() => {});
    fetch("/api/sym/universes", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: UniverseRef[]) => {
        setUniverses(d);
        if (d[0]) setUniverse(d[0].universe_id);
      })
      .catch(() => {});
    loadJobs();
  }, [loadJobs]);

  // Poll while any job is active.
  useEffect(() => {
    const active = jobs.some((j) => j.status === "queued" || j.status === "running");
    const id = setInterval(loadJobs, active ? 2000 : 6000);
    return () => clearInterval(id);
  }, [jobs, loadJobs]);

  async function run(op: OpDef) {
    const args = op.takes_universe ? [universe] : [];
    const r = await fetch("/api/operate/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: op.key, args, confirm }),
    });
    // Errors carry the spec'd envelope {error:{type,message}} (Story O.4);
    // `detail` remains as the legacy mirror during the migration.
    const res: RunResult & {
      detail?: string;
      error?: { type: string; message: string };
    } = await r.json();
    setMsg(
      r.ok
        ? `Started ${op.label} (job #${res.job_id})`
        : `Rejected: ${res.error?.message ?? res.detail ?? res.reason ?? "unknown"}`,
    );
    loadJobs();
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight text-fg">Operate</h1>
      <p className="mt-1 text-sm text-muted">
        Trigger sym&apos;s own idempotent operations as guarded background jobs (run out of the
        web process). Writers require confirmation; one run per operation at a time. sym&apos;s own
        run logs remain the system of record.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface p-3">
        <label className="text-sm text-muted">
          Universe{" "}
          <select
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm text-fg outline-none"
          >
            {universes.map((u) => (
              <option key={u.universe_id} value={u.universe_id}>
                {u.universe_id}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          confirm writers
        </label>
        {msg && <span className="text-xs text-muted">{msg}</span>}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {ops.map((op) => (
          <button
            key={op.key}
            onClick={() => run(op)}
            title={op.note}
            className={[
              "rounded-md border px-3 py-1.5 text-sm font-medium",
              op.writes
                ? "border-amber-500/40 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-300"
                : "border-border bg-fg/10 text-fg hover:bg-fg/20",
            ].join(" ")}
          >
            {op.label}
            {op.writes ? " ✎" : ""}
          </button>
        ))}
      </div>

      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">Recent jobs</h2>
      <div className="mt-3 overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Operation</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Exit</th>
              <th className="px-3 py-2 font-medium">Finished</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {jobs.map((j) => (
              <Fragment key={j.job_id}>
                <tr
                  className="cursor-pointer hover:bg-fg/5"
                  onClick={() => setOpen(open === j.job_id ? null : j.job_id)}
                >
                  <td className="px-3 py-2 tabular-nums text-muted">{j.job_id}</td>
                  <td className="px-3 py-2 font-medium text-fg">
                    {j.op}
                    {j.args.length ? ` ${j.args.join(" ")}` : ""}
                  </td>
                  <td className={`px-3 py-2 font-medium ${STATUS_STYLE[j.status] ?? "text-fg"}`}>
                    {j.status}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {j.exit_code ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {j.finished_at ? new Date(j.finished_at).toLocaleTimeString() : "—"}
                  </td>
                </tr>
                {open === j.job_id && (j.output || j.error) && (
                  <tr>
                    <td colSpan={5} className="bg-bg px-3 py-2">
                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs text-muted">
                        {j.error ? `${j.error}\n` : ""}
                        {j.output ?? ""}
                      </pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {jobs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-muted">
                  No jobs yet — trigger an operation above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
