"use client";

import { useEffect, useState } from "react";

type NewsItem = { title: string; link: string; source: string | null; published: string | null };

// Daily news for a security (Google News RSS via the API, fetched at serve time, not stored).
// Client-side + best-effort so the slow external feed never blocks the detail page's render.
export function NewsPanel({ figi }: { figi: string }) {
  const [items, setItems] = useState<NewsItem[] | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(`/api/sym/securities/${figi}/news`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((d: NewsItem[]) => {
        if (alive) setItems(Array.isArray(d) ? d : []);
      })
      .catch(() => {
        if (alive) setItems([]);
      });
    return () => {
      alive = false;
    };
  }, [figi]);

  return (
    <>
      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-muted">Recent news</h2>
      {items === null ? (
        <p className="mt-3 text-xs text-muted">Loading news…</p>
      ) : items.length === 0 ? (
        <p className="mt-3 text-xs text-muted">No recent news.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border overflow-hidden rounded-xl border border-border">
          {items.map((n, i) => (
            <li key={i} className="px-4 py-2 hover:bg-fg/5">
              <a
                href={n.link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-fg hover:underline"
              >
                {n.title}
              </a>
              <div className="text-[11px] text-muted">
                {[n.source, n.published ? new Date(n.published).toLocaleDateString() : null]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-muted">Headlines via Google News · opens the source in a new tab.</p>
    </>
  );
}
