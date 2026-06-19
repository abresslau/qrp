import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortfolioLive from "@/app/portfolios/[id]/live/page";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "7" }) }));

const PORTFOLIO = {
  portfolio_id: 7, name: "Long/Short Book", client: "Acme", base_currency: "USD",
  notional: null, created_at: null,
  as_of_dates: ["2026-06-05"], latest_as_of_date: "2026-06-05", shown_as_of_date: "2026-06-05",
  net_exposure: 0.6, gross_exposure: 1.0,
  weights: [
    { figi: "F1", ticker: "AAPL", name: "Apple", weight: 0.6 },
    { figi: "F2", ticker: "MSFT", name: "Microsoft", weight: 0.4 },
  ],
};

const COMP = {
  portfolio_id: 7, weights_as_of: "2026-06-05", as_of: "2026-06-19T14:30:00+00:00",
  freshness: "live", n_holdings: 2, n_priced: 2, total_weight: 1.0, net_weight: 0.6,
  holdings: [
    { figi: "F1", ticker: "AAPL", name: "Apple", sector: "Tech", industry: null, weight: 0.6, currency: "USD", price: 110, live_return: 0.1, freshness: "live" },
    { figi: "F2", ticker: "MSFT", name: "Microsoft", sector: "Tech", industry: null, weight: 0.4, currency: "USD", price: 120, live_return: 0.05, freshness: "live" },
  ],
  sectors: [{ sector: "Tech", weight: 1.0, n: 2, live_return: 0.08 }],
};

function json(body: unknown, ok = true, status = 200) {
  return Promise.resolve({ ok, status, json: () => Promise.resolve(body) });
}

function stub(opts: { compOk?: boolean } = {}) {
  const { compOk = true } = opts;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/composition"))
        return compOk
          ? json(COMP)
          : json({ error: { type: "unavailable", message: "quote provider unreachable" } }, false, 503);
      if (url.includes("/analytics/benchmarks")) return json([]);
      if (url.includes("/analytics/portfolios/") && url.includes("/live")) return json({ n_priced: 0, constituents: [] });
      if (url.includes("/analytics/portfolios/")) return json({ window: "ALL", returns: null, metrics: null, benchmark: null, portfolio_currencies: [], n_days: 0 });
      if (url.includes("/api/portfolios/7")) return json(PORTFOLIO);
      return json([]);
    }),
  );
}

beforeEach(() => stub());
afterEach(() => vi.unstubAllGlobals());

describe("PortfolioLive page", () => {
  it("renders the heat map and the sector/position pizza from one composition fetch", async () => {
    render(<PortfolioLive />);
    expect(await screen.findByText(/Long\/Short Book/)).toBeInTheDocument(); // header
    // pizza sector legend label is exactly "Tech" (heatmap sector header is "Tech  +8.00%")
    expect(screen.getByText("Tech")).toBeInTheDocument();
    // tickers appear in the heat-map tiles (and the position legend)
    expect(screen.getAllByText(/AAPL/).length).toBeGreaterThan(0);

    // exactly one composition fetch drives both visuals
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.filter((u) => u.includes("/composition")).length).toBe(1);
  });

  it("a 503 surfaces the error banner, not a blank page", async () => {
    stub({ compOk: false });
    render(<PortfolioLive />);
    expect(await screen.findByText(/Couldn.t load live composition/)).toBeInTheDocument();
    expect(screen.getByText(/← Portfolio/)).toBeInTheDocument(); // page chrome intact, recoverable
  });
});
