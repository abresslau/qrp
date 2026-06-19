import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioPizza } from "@/components/portfolio-pizza";

function holding(over: Record<string, unknown>) {
  return { figi: "F", ticker: "T", name: "n", sector: "Tech", industry: null, weight: 0.1, currency: "USD", price: 1, live_return: 0, freshness: "live", ...over };
}

const COMP: Composition = {
  portfolio_id: 1, weights_as_of: "2026-06-05", as_of: null, freshness: "live",
  n_holdings: 3, n_priced: 2, total_weight: 1.2, net_weight: 1.2,
  holdings: [
    holding({ figi: "F1", ticker: "AAPL", sector: "Tech", weight: 0.5, live_return: 0.1 }), // +0.05 winner
    holding({ figi: "F2", ticker: "INTC", sector: "Tech", weight: 0.4, live_return: -0.05 }), // -0.02 loser
    holding({ figi: "F3", ticker: "XOM", sector: "Energy", weight: 0.3, live_return: 0.01 }),
  ],
  sectors: [
    { sector: "Tech", weight: 0.9, n: 2, live_return: 0.05 },
    { sector: "Energy", weight: 0.3, n: 1, live_return: null }, // uncovered -> neutral, "—"
  ],
};

describe("PortfolioPizza — sector donut heat map", () => {
  it("renders one ring segment per sector with in-slice + legend labels (name, share%, daily P&L)", () => {
    render(<PortfolioPizza data={COMP} />);
    // name + daily P&L appear BOTH in-slice (like the heat map) and in the legend
    expect(screen.getAllByText("Tech").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Energy").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("+5.00%").length).toBeGreaterThanOrEqual(2); // Tech daily P&L
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2); // Energy uncovered -> neutral
    // share% is legend-only (one each)
    expect(screen.getByText("75.0%")).toBeInTheDocument(); // 0.9 / 1.2 share
    expect(screen.getByText("25.0%")).toBeInTheDocument(); // 0.3 / 1.2 share
  });

  it("colors each segment by daily P&L (one <path> per sector) and shows gross in the center", () => {
    const { container } = render(<PortfolioPizza data={COMP} />);
    expect(container.querySelectorAll("path").length).toBe(2); // 2 sectors -> 2 ring segments
    expect(screen.getByText("120.0%")).toBeInTheDocument(); // gross center
  });

  it("shows a quiet empty state when there are no sectors", () => {
    render(<PortfolioPizza data={{ ...COMP, sectors: [], total_weight: 0 }} />);
    expect(screen.getByText(/No holdings to slice yet/)).toBeInTheDocument();
  });

  it("hovering a sector slice shows its top winners/losers tooltip (≤5 names each)", async () => {
    const { container } = render(<PortfolioPizza data={COMP} />);
    const paths = container.querySelectorAll("path");
    fireEvent.mouseEnter(paths[0], { clientX: 100, clientY: 100 }); // first slice = Tech (largest)
    expect(await screen.findByText("Winners")).toBeInTheDocument();
    expect(screen.getByText("Losers")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument(); // Tech winner (+5% contribution)
    expect(screen.getByText("INTC")).toBeInTheDocument(); // Tech loser (−2% contribution)
    expect(screen.getByText(/Top 5 by daily/)).toBeInTheDocument();
  });
});
