import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioHeatmap, type Composition } from "@/components/portfolio-heatmap";

function comp(over: Partial<Composition> = {}): Composition {
  return {
    portfolio_id: 1, weights_as_of: "2026-06-05", as_of: "2026-06-19T14:30:00+00:00",
    freshness: "live", n_holdings: 3, n_priced: 2, total_weight: 1.0, net_weight: 0.4,
    holdings: [
      { figi: "F1", ticker: "AAPL", name: "Apple", sector: "Tech", industry: null, mic: "XNAS", country: "US", status: "active", weight: 0.6, currency: "USD", market_cap_usd: 1e9, volume: 1000, price: 110, live_return: 0.1, window_returns: {}, low_52w: null, high_52w: null, range_pct: null, freshness: "live" },
      { figi: "F2", ticker: "TSLA", name: "Tesla", sector: "Tech", industry: null, mic: "XNAS", country: "US", status: "active", weight: -0.3, currency: "USD", market_cap_usd: 1e9, volume: 1000, price: 90, live_return: -0.02, window_returns: {}, low_52w: null, high_52w: null, range_pct: null, freshness: "live" },
      { figi: "F3", ticker: "XYZ", name: "NoMap", sector: "Energy", industry: null, mic: null, country: null, status: null, weight: 0.1, currency: null, market_cap_usd: null, volume: null, price: null, live_return: null, window_returns: {}, low_52w: null, high_52w: null, range_pct: null, freshness: "unavailable" },
    ],
    sectors: [
      { sector: "Tech", weight: 0.9, n: 2, live_return: 0.06 },
      { sector: "Energy", weight: 0.1, n: 1, live_return: null },
    ],
    ...over,
  };
}

describe("PortfolioHeatmap", () => {
  it("renders a tile per holding (sized by position size)", () => {
    render(<PortfolioHeatmap data={comp()} />);
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
    expect(screen.getByText(/TSLA/)).toBeInTheDocument();
    expect(screen.getByText(/XYZ/)).toBeInTheDocument();
  });

  it("flags short positions with a dashed border", () => {
    const { container } = render(<PortfolioHeatmap data={comp()} />);
    // the short (TSLA, weight < 0) is the only tile with a dashed stroke
    const dashed = container.querySelectorAll("rect[stroke-dasharray]");
    expect(dashed.length).toBe(1);
  });

  it("shows a quiet empty state when there are no holdings", () => {
    render(<PortfolioHeatmap data={comp({ n_holdings: 0, holdings: [], sectors: [] })} />);
    expect(screen.getByText(/No holdings to map yet/)).toBeInTheDocument();
  });

  it("handles a null composition without crashing", () => {
    render(<PortfolioHeatmap data={null} />);
    expect(screen.getByText(/No holdings to map yet/)).toBeInTheDocument();
  });
});
