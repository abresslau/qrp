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

/** Price standardised to its currency's natural precision — exactly 2 dp for decimal currencies
 *  (USD/EUR/BRL/…), the currency's own precision for zero-decimal ones (JPY/KRW/…). Locale-grouped.
 *  `currency` is optional; without it (or for an unknown code) a decimal currency is assumed → 2 dp.
 *  NULL → "—". */
export function fmtPrice(v: number | null | undefined, currency?: string | null): string {
  if (v == null) return "—";
  let digits = 2;
  if (currency) {
    try {
      // ICU knows each currency's minor-unit count (JPY→0, USD→2); read it without the symbol.
      digits =
        new Intl.NumberFormat(undefined, {
          style: "currency",
          currency,
        }).resolvedOptions().maximumFractionDigits ?? 2;
    } catch {
      digits = 2; // unknown/invalid code → treat as a decimal currency
    }
  }
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
