import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioMovers } from "@/components/portfolio-movers";

function holding(over: Record<string, unknown>) {
  return { figi: "F", ticker: "T", name: "n", sector: "Tech", industry: null, weight: 0.1, currency: "USD", price: 1, live_return: 0, freshness: "live", ...over };
}

const COMP: Composition = {
  portfolio_id: 1, weights_as_of: null, as_of: null, freshness: "live",
  n_holdings: 3, n_priced: 3, total_weight: 1.0, net_weight: 0.6,
  holdings: [
    holding({ figi: "F1", ticker: "AAPL", weight: 0.5, live_return: 0.1 }), // +0.05 winner
    holding({ figi: "F2", ticker: "TSLA", weight: -0.2, live_return: 0.1 }), // -0.02 loser (short up)
    holding({ figi: "F3", ticker: "NVDA", weight: 0.3, live_return: -0.05 }), // -0.015 loser
  ],
  sectors: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("PortfolioMovers", () => {
  it("ranks Daily winners/losers by P&L contribution from the live composition (no fetch)", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<PortfolioMovers pid="1" composition={COMP} />);

    expect(screen.getByText("AAPL")).toBeInTheDocument(); // +5.00% contribution → winner
    expect(screen.getByText("TSLA")).toBeInTheDocument(); // short rallied → loser
    expect(screen.getByText("NVDA")).toBeInTheDocument(); // fell → loser
    expect(screen.getByText("+5.00%")).toBeInTheDocument(); // AAPL contribution
    expect((globalThis.fetch as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled(); // Daily = no fetch
  });

  it("fetches the attribution endpoint when switching to MTD", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              constituents: [
                { ticker: "XOM", ret: 0.2, contribution: 0.04 },
                { ticker: "BA", ret: -0.1, contribution: -0.03 },
              ],
            }),
        }),
      ),
    );
    render(<PortfolioMovers pid="1" composition={COMP} />);
    fireEvent.click(screen.getByText("MTD"));

    expect(await screen.findByText("XOM")).toBeInTheDocument(); // winner from MTD attribution
    expect(screen.getByText("BA")).toBeInTheDocument(); // loser
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes("/returns?window=MTD"))).toBe(true);
  });

  it("fetches a 1Y price sparkline when hovering a ticker", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve(
              url.includes("/prices")
                ? [
                    { session_date: "2026-01-01", close: 100 },
                    { session_date: "2026-06-01", close: 120 },
                  ]
                : { constituents: [] },
            ),
        }),
      ),
    );
    render(<PortfolioMovers pid="1" composition={COMP} />);
    fireEvent.mouseEnter(screen.getByText("AAPL")); // AAPL (figi F1) is a Daily winner
    expect(await screen.findByText("1Y price · close")).toBeInTheDocument(); // tooltip label
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes("/securities/F1/prices"))).toBe(true);
  });
});
