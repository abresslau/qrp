// Shared number formatters for the console. Kept in one place so the explorer list and
// the security-detail view render market cap / volume / price identically.

/** Compact magnitude: 3.0T / 1.6B / 51.0M / 1234. NULL → "—". */
export function fmtCompact(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return v.toFixed(0);
}

/** Price with up to 2 decimals, locale-grouped. NULL → "—". */
export function fmtPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
