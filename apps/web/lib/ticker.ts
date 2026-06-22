// Qualified-ticker formatting — render a bare ticker with its exchange/region acronym so same-ticker
// securities are distinguishable (ADS Adidas on Xetra vs ADS Bread Financial on NYSE). Three market
// conventions, all DERIVED from the exchange reference codes the API returns per security (never stored):
//   - bbg-region   "ADS GR"  ticker + Bloomberg composite/region code (exchange.exch_code)
//   - bbg-exchange "ADS GY"  ticker + Bloomberg primary-venue code   (exchange.bbg_exchange_code)
//   - factset      "ADS-DE"  ticker + FactSet region = ISO-3166 alpha-2 (exchange.country_iso)
//   - plain        "ADS"     the bare ticker
// Null-safe: a missing code degrades to the bare ticker (never "ADS null" / "ADS " / "ADS-").

export type TickerConvention = "bbg-region" | "bbg-exchange" | "factset" | "plain";

// The per-security exchange codes the API carries (all optional/nullable — honest fallback on absence).
export type TickerCodes = {
  ticker: string | null;
  exch_code?: string | null; // Bloomberg composite/region (GR, US, LN)
  bbg_exchange_code?: string | null; // Bloomberg primary venue (GY, UN, UW)
  country_iso?: string | null; // FactSet region / ISO-3166 alpha-2 (DE, US, GB)
};

export const TICKER_CONVENTIONS: { value: TickerConvention; label: string }[] = [
  { value: "bbg-region", label: "Bloomberg · Region" },
  { value: "bbg-exchange", label: "Bloomberg · Exchange" },
  { value: "factset", label: "FactSet" },
  { value: "plain", label: "Plain ticker" },
];

export function qualifiedTicker(c: TickerCodes, convention: TickerConvention): string {
  const t = (c.ticker ?? "").trim();
  if (!t) return "—";
  // Trim the codes too (a whitespace-only code is truthy but would render "ADS " / "ADS- ").
  switch (convention) {
    case "bbg-region": {
      const region = c.exch_code?.trim();
      return region ? `${t} ${region}` : t;
    }
    case "bbg-exchange": {
      const venue = c.bbg_exchange_code?.trim();
      return venue ? `${t} ${venue}` : t;
    }
    case "factset": {
      const fsr = c.country_iso?.trim();
      return fsr ? `${t}-${fsr}` : t;
    }
    default:
      return t;
  }
}

// All three qualified forms (for a tooltip), skipping any whose code is absent. Bare ticker if none.
export function allQualifiedTickers(c: TickerCodes): string {
  const forms = [
    ["Bloomberg (region)", qualifiedTicker(c, "bbg-region")],
    ["Bloomberg (exchange)", qualifiedTicker(c, "bbg-exchange")],
    ["FactSet", qualifiedTicker(c, "factset")],
  ] as const;
  const t = (c.ticker ?? "").trim();
  const seen = forms.filter(([, v]) => v !== t && v !== "—");
  if (!seen.length) return t || "—";
  return seen.map(([label, v]) => `${label}: ${v}`).join("\n");
}
