import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioPivot } from "@/components/portfolio-pivot";

function holding(over: Record<string, unknown>) {
  return {
    figi: "F", ticker: "T", name: "n", sector: "Tech", industry: null, mic: "XNAS",
    country: "United States", status: "active", weight: 0.1, currency: "USD",
    market_cap_usd: 1e12, volume: 1_000_000, price: 100, live_return: 0, freshness: "live",
    ...over,
  };
}

const COMP: Composition = {
  portfolio_id: 1, weights_as_of: "2026-06-05", as_of: null, freshness: "live",
  n_holdings: 3, n_priced: 3, total_weight: 1.2, net_weight: 1.2,
  holdings: [
    holding({ figi: "F1", ticker: "AAPL", sector: "Tech", weight: 0.5, live_return: 0.1 }), // +4.17%
    holding({ figi: "F2", ticker: "INTC", sector: "Tech", weight: 0.4, live_return: -0.05 }), // −1.67%
    holding({ figi: "F3", ticker: "XOM", sector: "Energy", country: "United States", weight: 0.3, live_return: 0.01 }),
  ],
  sectors: [
    { sector: "Tech", weight: 0.9, n: 2, live_return: 0.0333 },
    { sector: "Energy", weight: 0.3, n: 1, live_return: 0.01 },
  ],
};

describe("PortfolioPivot", () => {
  it("renders explorer columns, sector groups, per-stock rows and a Total = Daily P&L", () => {
    render(<PortfolioPivot data={COMP} />);
    // explorer-style column headers
    for (const h of ["Ticker", "Country", "Exch", "Ccy", "Price", "Mkt cap", "Volume", "Return", "P&L"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    // sector groups + stock rows
    expect(screen.getAllByText("Tech").length).toBeGreaterThan(0);
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("XOM")).toBeInTheDocument();
    expect(screen.getAllByText("United States").length).toBeGreaterThan(0);
    // total row sums contributions to the Daily P&L (+2.75%)
    expect(screen.getByText(/Total · 3 holdings/)).toBeInTheDocument();
    expect(screen.getByText("+2.75%")).toBeInTheDocument();
  });

  it("shows an empty state with no holdings", () => {
    render(<PortfolioPivot data={{ ...COMP, holdings: [] }} />);
    expect(screen.getByText(/No holdings yet/)).toBeInTheDocument();
  });
});
