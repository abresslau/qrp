import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioPizza } from "@/components/portfolio-pizza";

function holding(over: Record<string, unknown>) {
  return { figi: "F", ticker: "T", name: "n", sector: "Tech", industry: null, mic: "XNAS", country: "US", status: "active", weight: 0.1, currency: "USD", market_cap_usd: 1e9, volume: 1000, price: 1, live_return: 0, window_returns: {}, low_52w: null, high_52w: null, range_pct: null, freshness: "live", ...over };
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
  it("labels each sector by its daily P&L CONTRIBUTION in-slice + legend (sums to Daily P&L)", () => {
    render(<PortfolioPizza data={COMP} />);
    // covered = 0.5+0.4+0.3 = 1.2. Tech contrib = (0.5·0.1 + 0.4·−0.05)/1.2 = +2.50%; Energy = +0.25%.
    expect(screen.getAllByText("Tech").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Energy").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("+2.50%").length).toBeGreaterThanOrEqual(2); // Tech contribution, in-slice + legend
    expect(screen.getAllByText("+0.25%").length).toBeGreaterThanOrEqual(2); // Energy contribution
    expect(screen.getByText("75.0%")).toBeInTheDocument(); // Tech weight (0.9 / 1.2)
    expect(screen.getByText("25.0%")).toBeInTheDocument(); // Energy weight (0.3 / 1.2)
  });

  it("has column headers and a Total row that sums to Daily P&L", () => {
    render(<PortfolioPizza data={COMP} />);
    expect(screen.getByText("Sector")).toBeInTheDocument();
    expect(screen.getByText("Wt")).toBeInTheDocument();
    expect(screen.getByText("P&L")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("+2.75%")).toBeInTheDocument(); // Σ contributions = Daily P&L
  });

  it("colors each segment by daily P&L (one <path> per sector) and shows gross in the center", () => {
    const { container } = render(<PortfolioPizza data={COMP} />);
    expect(container.querySelectorAll("path").length).toBe(2); // 2 sectors -> 2 ring segments
    expect(screen.getByText("120.0%")).toBeInTheDocument(); // gross center
  });

  // A book with a small (4%) third sector that's below the small-screen label cutoff (6%) but above
  // the large-screen cutoff — used to prove the donut labels more sectors when it grows.
  const COMP_SMALL_SECTOR: Composition = {
    ...COMP,
    total_weight: 1.0,
    holdings: [holding({ figi: "F1", sector: "Tech", weight: 0.5, live_return: 0.01 })],
    sectors: [
      { sector: "Tech", weight: 0.5, n: 1, live_return: 0.01 },
      { sector: "Health", weight: 0.46, n: 1, live_return: 0.01 },
      { sector: "Energy", weight: 0.04, n: 1, live_return: 0.01 }, // frac 0.04: <6% small, ≥3.5% large
    ],
  };
  // Find the in-svg label <g> for a sector by its text content (the slice <path>s carry no text).
  const labelGroupFor = (container: HTMLElement, sector: string) =>
    Array.from(container.querySelectorAll("svg g")).find((g) => g.textContent?.includes(sector));

  it("sizes the donut by its CONTAINER (container-query class, not viewport)", () => {
    const { container } = render(<PortfolioPizza data={COMP} />);
    const root = container.firstElementChild as HTMLElement; // the pizza root <div>
    expect(root.getAttribute("class") ?? "").toContain("@container"); // establishes a query container
    const svgCls = container.querySelector("svg")!.getAttribute("class") ?? "";
    expect(svgCls).toMatch(/@\w+:[hw]-/); // grows at container breakpoints (e.g. @xl:w-72)
    expect(svgCls).not.toMatch(/(?<!@)\blg:[hw]-/); // no plain viewport lg: variant (only @lg: container)
  });

  it("renders minor-sector labels but CSS-gates them to wide containers; majors always show", () => {
    const { container } = render(<PortfolioPizza data={COMP_SMALL_SECTOR} />);
    // Energy (4%) is a minor slice: its label is in the DOM but hidden until the container is wide.
    const energy = labelGroupFor(container, "Energy");
    expect(energy).toBeTruthy();
    const energyCls = energy!.getAttribute("class") ?? "";
    expect(energyCls).toContain("hidden"); // hidden by default…
    expect(energyCls).toContain("@2xl:block"); // …shown only when the container is wide (catch a typo'd variant)
    // Tech (50%) is major: its label is always shown (not gated).
    const major = labelGroupFor(container, "Tech");
    expect(major!.getAttribute("class") ?? "").not.toContain("hidden");
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
