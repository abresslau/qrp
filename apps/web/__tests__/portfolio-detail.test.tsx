import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortfolioDetail from "@/app/portfolios/[id]/page";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "7" }) }));

const PORTFOLIO = {
  portfolio_id: 7, name: "Long/Short Book", client: "Acme", base_currency: "USD",
  notional: null, created_at: null,
  as_of_dates: ["2026-06-05"], latest_as_of_date: "2026-06-05", shown_as_of_date: "2026-06-05",
  net_exposure: 1.0, gross_exposure: 1.2,
  weights: [
    { figi: "F1", ticker: "AAPL", name: "Apple", weight: 0.6 },
    { figi: "F2", ticker: "MSFT", name: "Microsoft", weight: 0.5 },
    { figi: "F3", ticker: "TSLA", name: "Tesla", weight: -0.1 },
  ],
};

function json(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/return-windows")) return json([{ code: "YTD", label: "YTD" }]);
      if (url.includes("/returns")) return json({ window: "YTD", as_of_date: "2026-06-05", constituents: [], covered_weight: 0, n_with_return: 0, n_constituents: 3, portfolio_return: null, portfolio_return_normalized: null });
      if (url.includes("/analytics/benchmarks")) return json([]);
      if (url.includes("/live")) return json({ n_priced: 0, constituents: [] });
      if (url.includes("/analytics/portfolios/")) return json({ window: "ALL", returns: null, metrics: null, benchmark: null, portfolio_currencies: [], n_days: 0 });
      if (url.includes("/api/portfolios/7")) return json(PORTFOLIO);
      return json([]);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("PortfolioDetail — exposure + analytics-first layout", () => {
  it("renders net & gross exposure at the top", async () => {
    render(<PortfolioDetail />);
    expect(await screen.findByText("Net exp.")).toBeInTheDocument();
    expect(screen.getByText("Gross exp.")).toBeInTheDocument();
    expect(screen.getByText("+100.00%")).toBeInTheDocument(); // net 1.0
    expect(screen.getByText("120.0%")).toBeInTheDocument(); // gross 1.2
  });

  it("renders Risk & return analytics ABOVE the holdings table", async () => {
    render(<PortfolioDetail />);
    const analytics = await screen.findByText("Risk & return analytics");
    const holdings = await screen.findByText(/^Holdings/);
    // analytics precedes holdings in document order (DOCUMENT_POSITION_FOLLOWING = 4)
    expect(analytics.compareDocumentPosition(holdings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
