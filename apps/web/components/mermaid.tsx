"use client";

import { useEffect, useRef, useState } from "react";

// Renders a Mermaid `flowchart` source to SVG, client-side. `mermaid` is dynamically imported
// inside the effect so it never runs during SSR and isn't in the initial bundle.
export function Mermaid({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });
        const id = "m" + Math.random().toString(36).slice(2);
        const { svg } = await mermaid.render(id, chart);
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (err) return <pre className="whitespace-pre-wrap text-xs text-rose-400">{err}</pre>;
  return <div ref={ref} className="overflow-x-auto [&_svg]:max-w-full" />;
}
