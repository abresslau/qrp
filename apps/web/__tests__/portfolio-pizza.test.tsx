import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioPizza } from "@/components/portfolio-pizza";

// 14 holdings so the "By position size" donut collapses the tail (>12) into one "Other" slice.
function holdings() {
  return Array.from({ length: 14 }, (_, i) => ({
    figi: `F${i}`, ticker: `T${i}`, name: `Name ${i}`, sector: i < 10 ? "Tech" : "Energy",
    industry: null, weight: 0.1 - i * 0.005, currency: "USD",
    price: 100, live_return: 0.01, freshness: "live",
  }));
}

const COMP: Composition = {
  portfolio_id: 1, weights_as_of: "2026-06-05", as_of: null, freshness: "live",
  n_holdings: 14, n_priced: 14, total_weight: 1.2, net_weight: 0.6,
  holdings: holdings(),
  sectors: [
    { sector: "Tech", weight: 0.9, n: 10, live_return: 0.05 },
    { sector: "Energy", weight: 0.3, n: 4, live_return: null },
  ],
};

describe("PortfolioPizza", () => {
  it("renders the sector breakdown with one share% off gross", () => {
    render(<PortfolioPizza data={COMP} />);
    // Slice label is the sector name; the share% (slice ÷ chart total = gross) is the legend column.
    expect(screen.getByText("Tech")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument(); // 0.9 / 1.2 gross
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument(); // 0.3 / 1.2 gross
  });

  it("collapses positions beyond the top-N into an 'Other' slice", () => {
    render(<PortfolioPizza data={COMP} />);
    expect(screen.getByText("Other (2)")).toBeInTheDocument(); // 14 − 12 = 2
    expect(screen.getByText("T0")).toBeInTheDocument(); // largest position is a named slice
  });

  it("shows gross and net in the donut centers", () => {
    render(<PortfolioPizza data={COMP} />);
    expect(screen.getByText("120.0%")).toBeInTheDocument(); // gross (sector donut center)
    expect(screen.getByText("60.0%")).toBeInTheDocument(); // net (position donut center)
    expect(screen.getByText(/names · net/)).toBeInTheDocument();
  });

  it("shows a quiet empty state when there are no holdings", () => {
    render(<PortfolioPizza data={{ ...COMP, n_holdings: 0, holdings: [], sectors: [] }} />);
    expect(screen.getByText(/No holdings to slice yet/)).toBeInTheDocument();
  });
});
