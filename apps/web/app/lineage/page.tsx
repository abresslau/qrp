"use client";

import { useEffect, useMemo, useState } from "react";

import { Mermaid } from "@/components/mermaid";
import type { Schemas } from "@/lib/api";

type Graph = Schemas["LineageGraph"];
type FieldFlows = Schemas["FieldFlows"];

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-border px-3 py-1.5">
      <div className="text-lg font-semibold tabular-nums text-fg">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

export default function LineagePage() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [flows, setFlows] = useState<FieldFlows | null>(null);

  useEffect(() => {
    fetch("/api/lineage/graph", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: Graph) => setGraph(d))
      .catch(() => setGraph(null));
    fetch("/api/lineage/field-flow", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: FieldFlows) => setFlows(d))
      .catch(() => setFlows(null));
  }, []);

  const dagsterUrl = graph?.dagster_url ?? flows?.dagster_url ?? "http://127.0.0.1:3333";

  // Dedup the table-level edges by source->target (an edge can be both declared and referential),
  // collect the distinct bases, then group by the downstream package.
  const byGroup = useMemo(() => {
    type Row = { source: string; target: string; group: string; bases: Set<string> };
    const merged = new Map<string, Row>();
    for (const e of graph?.edges ?? []) {
      const k = `${e.source} ${e.target}`;
      const cur: Row = merged.get(k) ?? {
        source: e.source,
        target: e.target,
        group: e.target_group ?? "other",
        bases: new Set<string>(),
      };
      cur.bases.add(e.basis.split(" ")[0]);
      merged.set(k, cur);
    }
    const groups: Record<string, Row[]> = {};
    for (const e of merged.values()) (groups[e.group] ??= []).push(e);
    return groups;
  }, [graph]);

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">lineage</h1>
      <p className="mt-1 text-sm text-muted">
        Data lineage across the QRP packages — auto-derived from each loader&apos;s SQL plus
        Postgres foreign keys (sym is a peer: a common read-only upstream). The interactive graph
        lives in Dagster; this is the table-level view and the join-key field flow.
      </p>

      {graph && (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Stat label="assets" value={graph.stats.assets} />
          <Stat label="edges" value={graph.stats.edges} />
          {Object.entries(graph.stats.by_basis).map(([b, n]) => (
            <Stat key={b} label={b} value={n} />
          ))}
          <a
            href={dagsterUrl}
            target="_blank"
            rel="noreferrer"
            className="ml-auto rounded-lg border border-border px-3 py-2 text-sm text-fg hover:bg-fg/5"
          >
            Open interactive graph in Dagster →
          </a>
        </div>
      )}

      <h2 className="mt-8 text-sm font-semibold text-fg">Join-key field flow</h2>
      <div className="mt-3 grid gap-5 lg:grid-cols-2">
        {(flows?.flows ?? []).map((f) => (
          <div key={f.key} className="rounded-xl border border-border bg-surface p-4">
            <div className="mb-2 font-mono text-xs text-muted">{f.key}</div>
            <Mermaid chart={f.mermaid} />
          </div>
        ))}
        {!flows && <p className="text-sm text-muted">Loading field flow…</p>}
      </div>

      <h2 className="mt-8 text-sm font-semibold text-fg">Table-level edges</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Object.entries(byGroup)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([g, es]) => (
            <div key={g} className="rounded-xl border border-border p-3">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{g}</div>
              <ul className="space-y-1 text-sm">
                {es.map((e) => (
                  <li key={`${e.source} ${e.target}`} className="flex items-baseline gap-2">
                    <span className="text-fg">
                      {e.source} <span className="text-muted">→</span> {e.target}
                    </span>
                    <span className="ml-auto text-[10px] text-muted">{[...e.bases].join("·")}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        {!graph && <p className="text-sm text-muted">Loading edges…</p>}
      </div>
    </div>
  );
}
