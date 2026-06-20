import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioPivot } from "@/components/portfolio-pivot";

function holding(over: Record<string, unknown>) {
  return {
    figi: "F", ticker: "T", name: "n", sector: "Tech", industry: null, mic: "XNAS",
    country: "United States", status: "active", weight: 0.1, currency: "USD",
    market_cap_usd: 1e12, volume: 1_000_000, price: 100, live_return: 0,
    window_returns: { "1D": 0, "1M": 0, "3M": 0, "6M": 0 },
    low_52w: null, high_52w: null, range_pct: null, freshness: "live",
    ...over,
  };
}

const COMP: Composition = {
  portfolio_id: 1, weights_as_of: "2026-06-05", as_of: null, freshness: "live",
  n_holdings: 3, n_priced: 3, total_weight: 1.2, net_weight: 1.2,
  holdings: [
    holding({ figi: "F1", ticker: "AAPL", sector: "Tech", weight: 0.5, live_return: 0.1,
      window_returns: { "1D": 0.0123, "1M": 0.05, "3M": -0.02, "6M": null },
      low_52w: 50, high_52w: 150, range_pct: 0.75 }), // +4.17%; 75% up its 52w range
    holding({ figi: "F2", ticker: "INTC", sector: "Tech", weight: 0.4, live_return: -0.05 }), // −1.67%
    holding({ figi: "F3", ticker: "XOM", sector: "Energy", country: "United States", weight: 0.3, live_return: 0.01 }),
  ],
  sectors: [
    { sector: "Tech", weight: 0.9, n: 2, live_return: 0.0333 },
    { sector: "Energy", weight: 0.3, n: 1, live_return: 0.01 },
  ],
};

describe("PortfolioPivot", () => {
  it("renders explorer columns, sector groups, per-stock rows and a Daily P&L grand total", () => {
    render(<PortfolioPivot data={COMP} />);
    // explorer-style + P&L column headers (no orphan Return / generic P&L columns)
    for (const h of ["Ticker", "Country", "Exch", "Ccy", "Price", "52-week range", "Daily P&L", "MTD P&L", "YTD P&L", "Mkt cap", "Volume"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    expect(screen.queryByText("Return")).not.toBeInTheDocument();
    // sector groups + stock rows
    expect(screen.getAllByText("Tech").length).toBeGreaterThan(0);
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("XOM")).toBeInTheDocument();
    expect(screen.getAllByText("United States").length).toBeGreaterThan(0);
    // Daily P&L grand total = Σ weight·live_return (FX-hedged, no normalisation):
    // 0.5·0.1 + 0.4·(−0.05) + 0.3·0.01 = +3.30%
    expect(screen.getByText(/Total · 3 holdings/)).toBeInTheDocument();
    expect(screen.getByText("+3.30%")).toBeInTheDocument();
  });

  it("renders the trailing return columns then the Daily/MTD/YTD P&L contribution columns", () => {
    render(<PortfolioPivot data={COMP} />);
    // column order after Price: the four return windows, then the three P&L contribution columns
    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    const i = headers.indexOf("Price");
    expect(headers.slice(i, i + 10)).toEqual([
      "Price", "1D Chg", "1M Return", "3M Return", "6M Return", "52-week range",
      "Daily P&L", "MTD P&L", "YTD P&L", "Mkt cap",
    ]);
    // the header row carries all 17 columns (5 explorer + Wt + Price + 4 windows + 52W Range + 3 P&L + MktCap + Vol)
    const headerCells = screen.getAllByRole("row")[0].querySelectorAll("th");
    expect(headerCells).toHaveLength(17);
    // AAPL row, by position: returns render re-based (null 6M -> —); 52W Range bar; Daily P&L = weight·live_return
    const cells = Array.from(screen.getByText("AAPL").closest("tr")!.querySelectorAll("td")).map(
      (td) => td.textContent,
    );
    expect(cells[7]).toBe("+1.23%"); // 1D return
    expect(cells[8]).toBe("+5.00%"); // 1M return
    expect(cells[9]).toBe("-2.00%"); // 3M return
    expect(cells[10]).toBe("—"); // 6M null
    expect(cells[11]).not.toBe("—"); // 52W Range bar present (F1 has extremes)
    expect(cells[11]).toContain("150"); // shows the 52w high endpoint label
    expect(cells[12]).toBe("+5.00%"); // Daily P&L = 0.5 × live_return 0.1
    expect(cells[13]).toBe("—"); // MTD P&L (no MTD return on F1)
  });

  it("shows an empty state with no holdings", () => {
    render(<PortfolioPivot data={{ ...COMP, holdings: [] }} />);
    expect(screen.getByText(/No holdings yet/)).toBeInTheDocument();
  });
});
