import { apiGet } from "@/lib/api";

type Review = {
  review_id: string;
  source_key: string | null;
  source_input: string | null;
  status: string | null;
  created_at: string | null;
};
type Gap = {
  figi: string;
  ticker: string | null;
  session_date: string | null;
  source: string | null;
  detected_at: string | null;
};
type Prop = {
  proposal_id: string;
  universe_id: string | null;
  raw_identifier: string | null;
  change: string | null;
  status: string | null;
};
type Attention = {
  review_queue: Review[];
  price_gaps: { total: number; recent: Gap[] };
  membership_proposals: Prop[];
};

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">
        {title} <span className="ml-1 tabular-nums text-fg">{count.toLocaleString()}</span>
      </h2>
      {children}
    </section>
  );
}

export default async function AttentionPage() {
  let a: Attention | null = null;
  try {
    a = await apiGet<Attention>("/api/sym/attention");
  } catch {
    a = null;
  }
  if (!a) {
    return (
      <div>
        <h1 className="text-lg font-semibold text-fg">Attention</h1>
        <p className="mt-3 text-sm text-rose-600 dark:text-rose-400">API unreachable.</p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Attention</h1>
      <p className="mt-1 text-sm text-muted">
        Items sym flagged for review. Read‑only — resolve via sym&apos;s own review/confirm
        operations (acting from QRP is post‑v1).
      </p>

      <Section title="Securities review queue" count={a.review_queue.length}>
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Input</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 text-right font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {a.review_queue.map((r) => (
                <tr key={r.review_id} className="hover:bg-fg/5">
                  <td className="px-4 py-2 text-fg">{r.source_key ?? "—"}</td>
                  <td className="px-4 py-2 text-muted">{r.source_input ?? "—"}</td>
                  <td className="px-4 py-2 text-muted">{r.status ?? "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted">
                    {r.created_at ? r.created_at.slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
              {a.review_queue.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-5 text-center text-muted">
                    Nothing in the review queue.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Price gaps" count={a.price_gaps.total}>
        <div className="mb-2 text-xs text-muted">
          Showing the {a.price_gaps.recent.length} most recently detected.{" "}
          <span className="text-fg">Fix:</span> run sym <code className="font-mono">load</code>/
          <code className="font-mono">recompute</code> to fill.
        </div>
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Security</th>
                <th className="px-4 py-2 font-medium">Session</th>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 text-right font-medium">Detected</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {a.price_gaps.recent.map((g, i) => (
                <tr key={`${g.figi}-${g.session_date}-${i}`} className="hover:bg-fg/5">
                  <td className="px-4 py-2 font-medium text-fg">{g.ticker ?? g.figi}</td>
                  <td className="px-4 py-2 tabular-nums text-muted">{g.session_date ?? "—"}</td>
                  <td className="px-4 py-2 text-muted">{g.source ?? "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-muted">
                    {g.detected_at ? g.detected_at.slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Universe membership proposals" count={a.membership_proposals.length}>
        {a.membership_proposals.length === 0 ? (
          <div className="rounded-xl border border-border bg-surface px-4 py-5 text-sm text-muted">
            No pending membership proposals.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface text-left text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Universe</th>
                  <th className="px-4 py-2 font-medium">Identifier</th>
                  <th className="px-4 py-2 font-medium">Change</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {a.membership_proposals.map((p) => (
                  <tr key={p.proposal_id} className="hover:bg-fg/5">
                    <td className="px-4 py-2 text-fg">{p.universe_id ?? "—"}</td>
                    <td className="px-4 py-2 text-muted">{p.raw_identifier ?? "—"}</td>
                    <td className="px-4 py-2 text-muted">{p.change ?? "—"}</td>
                    <td className="px-4 py-2 text-muted">{p.status ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
