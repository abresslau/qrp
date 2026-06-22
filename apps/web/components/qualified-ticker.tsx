"use client";

// A client island that renders a ticker qualified by the user's chosen convention (shared store),
// with an all-three-forms tooltip. Lets server components (e.g. the security detail page) show the
// convention-aware ticker by passing the per-security exchange codes as props.

import { allQualifiedTickers, qualifiedTicker, type TickerCodes } from "@/lib/ticker";
import { useTickerConvention } from "@/lib/ticker-convention";

export function QualifiedTicker({ codes, className }: { codes: TickerCodes; className?: string }) {
  const convention = useTickerConvention();
  return (
    <span className={className} title={allQualifiedTickers(codes)}>
      {qualifiedTicker(codes, convention)}
    </span>
  );
}
