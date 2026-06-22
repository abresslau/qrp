import { describe, expect, it } from "vitest";

import { allQualifiedTickers, qualifiedTicker } from "@/lib/ticker";

const ADIDAS = { ticker: "ADS", exch_code: "GR", bbg_exchange_code: "GY", country_iso: "DE" };
const BREAD = { ticker: "ADS", exch_code: "US", bbg_exchange_code: "UN", country_iso: "US" };

describe("qualifiedTicker", () => {
  it("disambiguates same-ticker securities across the three conventions", () => {
    // the whole point: ADS Adidas (Xetra) vs ADS Bread Financial (NYSE)
    expect(qualifiedTicker(ADIDAS, "bbg-region")).toBe("ADS GR");
    expect(qualifiedTicker(ADIDAS, "bbg-exchange")).toBe("ADS GY");
    expect(qualifiedTicker(ADIDAS, "factset")).toBe("ADS-DE");
    expect(qualifiedTicker(BREAD, "bbg-region")).toBe("ADS US");
    expect(qualifiedTicker(BREAD, "bbg-exchange")).toBe("ADS UN");
    expect(qualifiedTicker(BREAD, "factset")).toBe("ADS-US");
    // venue distinguishes two same-region (US) listings: NYSE UN vs Nasdaq UW
    expect(qualifiedTicker({ ticker: "ADS", exch_code: "US", bbg_exchange_code: "UW" }, "bbg-exchange")).toBe("ADS UW");
  });

  it("plain returns the bare ticker", () => {
    expect(qualifiedTicker(ADIDAS, "plain")).toBe("ADS");
  });

  it("falls back to the bare ticker when a code is missing (never 'ADS null' / 'ADS-')", () => {
    const noVenue = { ticker: "FOO", exch_code: "GR", bbg_exchange_code: null, country_iso: "DE" };
    expect(qualifiedTicker(noVenue, "bbg-exchange")).toBe("FOO"); // missing venue → bare
    expect(qualifiedTicker(noVenue, "bbg-region")).toBe("FOO GR"); // region present
    const bare = { ticker: "BAR", exch_code: null, bbg_exchange_code: null, country_iso: null };
    expect(qualifiedTicker(bare, "factset")).toBe("BAR");
    expect(qualifiedTicker(bare, "bbg-region")).toBe("BAR");
  });

  it("treats a whitespace-only code as absent (never 'ADS ' / 'ADS- ')", () => {
    const wsp = { ticker: "ADS", exch_code: " ", bbg_exchange_code: "  ", country_iso: " " };
    expect(qualifiedTicker(wsp, "bbg-region")).toBe("ADS");
    expect(qualifiedTicker(wsp, "bbg-exchange")).toBe("ADS");
    expect(qualifiedTicker(wsp, "factset")).toBe("ADS");
  });

  it("returns an em dash for a null/empty ticker", () => {
    expect(qualifiedTicker({ ticker: null }, "bbg-region")).toBe("—");
    expect(qualifiedTicker({ ticker: "  " }, "plain")).toBe("—");
  });
});

describe("allQualifiedTickers (tooltip)", () => {
  it("lists every form whose code is present", () => {
    const t = allQualifiedTickers(ADIDAS);
    expect(t).toContain("Bloomberg (region): ADS GR");
    expect(t).toContain("Bloomberg (exchange): ADS GY");
    expect(t).toContain("FactSet: ADS-DE");
  });

  it("falls back to the bare ticker when no codes are present", () => {
    expect(allQualifiedTickers({ ticker: "BAR" })).toBe("BAR");
  });
});
