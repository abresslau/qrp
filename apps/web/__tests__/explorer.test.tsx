import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ExplorerPage from "@/app/sym/explorer/page";

function row(over: Record<string, unknown> = {}) {
  return {
    figi: "F1", ticker: "AAPL", name: "Apple Inc", mic: "XNAS", currency: "USD", status: "active",
    price: 296.42, session_date: "2026-06-17", volume: 51000000,
    market_cap_usd: 3.0e12, country: "United States", country_iso: "US",
    sector: "Information Technology",
    ...over,
  };
}

const RESP = {
  total: 2,
  limit: 50,
  offset: 0,
  rows: [
    row(),
    // a security with no price / fundamentals / classification / exchange row
    row({
      figi: "F2", ticker: "OBSCURE", name: "Obscure Co", mic: null, currency: null, status: "active",
      price: null, session_date: null, volume: null, market_cap_usd: null,
      country: null, country_iso: null, sector: null,
    }),
  ],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      // the page now also fetches the universe list for the filter dropdown
      const body = url.includes("/universes") ? [] : RESP;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("ExplorerPage enrichment", () => {
  it("renders the new enrichment columns and values", async () => {
    render(<ExplorerPage />);

    // new column headers
    for (const h of ["Sector", "Country", "Price", "Volume", "Mkt cap"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    // populated row values (formatted)
    expect(await screen.findByText("296.42")).toBeInTheDocument(); // price
    expect(screen.getByText("51.0M")).toBeInTheDocument(); // volume
    expect(screen.getByText("$3.00T")).toBeInTheDocument(); // market cap
    expect(screen.getByText("Information Technology")).toBeInTheDocument(); // sector
    expect(screen.getByText("US")).toBeInTheDocument(); // country_iso
  });

  it("degrades null enrichment to em-dashes (the unpriced/unclassified row)", async () => {
    render(<ExplorerPage />);
    await screen.findByText("OBSCURE"); // the null row mounted
    // the null row's enrichment cells must each degrade: sector, country, mic, ccy, price,
    // volume, mkt cap = 7 em-dashes from that one row (the populated row contributes none).
    // A count this high fails if any new enrichment cell stopped degrading to "—".
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(7);
  });

  it("renders the universe filter dropdown with options", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const body = url.includes("/universes")
          ? [{ universe_id: "sp500", name: "S&P 500", members_resolved: 650 }]
          : RESP;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      }),
    );
    render(<ExplorerPage />);
    expect(await screen.findByText("All universes")).toBeInTheDocument();
    expect(await screen.findByText("S&P 500 (650)")).toBeInTheDocument();
  });
});
