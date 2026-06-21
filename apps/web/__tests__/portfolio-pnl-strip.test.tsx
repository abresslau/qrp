import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioPnlStrip } from "@/components/portfolio-pnl-strip";
import type { Schemas } from "@/lib/api";

type Portfolio = Schemas["PortfolioDetail"];

function portfolio(over: Partial<Portfolio> = {}): Portfolio {
  return {
    portfolio_id: 7, name: "Book", client: "Acme", base_currency: "USD", notional: null,
    created_at: null, as_of_dates: ["2026-06-05"], latest_as_of_date: "2026-06-05",
    shown_as_of_date: "2026-06-05",
    net_exposure: 0.6, gross_exposure: 1.0, long_exposure: 0.8, short_exposure: 0.2,
    weights: [],
    ...over,
  };
}

// Daily/MTD/YTD are plain props (Σ weight·return from the composition) — no fetch.
const RETURNS = { dailyReturn: 0.0164, mtdReturn: -0.0391, ytdReturn: 0.1212 };

describe("PortfolioPnlStrip", () => {
  it("shows Daily/MTD/YTD return-space P&L when no notional is set", () => {
    render(<PortfolioPnlStrip portfolio={portfolio()} {...RETURNS} />);

    expect(screen.getByText("Daily P&L")).toBeInTheDocument();
    expect(screen.getByText("MTD P&L")).toBeInTheDocument();
    expect(screen.getByText("YTD P&L")).toBeInTheDocument();
    expect(screen.getByText("+1.64%")).toBeInTheDocument(); // daily (composition roll-up)
    expect(screen.getByText("-3.91%")).toBeInTheDocument(); // MTD
    expect(screen.getByText("+12.12%")).toBeInTheDocument(); // YTD
  });

  it("no longer renders the risk/exposure stats (Long/Short/Net/Gross/L/S)", () => {
    render(<PortfolioPnlStrip portfolio={portfolio()} {...RETURNS} />);
    expect(screen.queryByText("L/S")).not.toBeInTheDocument();
    expect(screen.queryByText("Long")).not.toBeInTheDocument();
    expect(screen.queryByText("Short")).not.toBeInTheDocument();
    expect(screen.queryByText("Net")).not.toBeInTheDocument();
    expect(screen.queryByText("Gross")).not.toBeInTheDocument();
  });

  it("shows the % return AND the base-currency P&L amount when a notional is set", () => {
    render(<PortfolioPnlStrip portfolio={portfolio({ notional: 1_000_000 })} {...RETURNS} />);
    expect(screen.getByText("+1.64%")).toBeInTheDocument(); // % return still shown
    // amounts = return × notional (Daily/MTD/YTD all derived the same way)
    expect(screen.getByText("+USD 16.4K")).toBeInTheDocument(); // daily = 0.0164 × 1M
    expect(screen.getByText("−USD 39.1K")).toBeInTheDocument(); // MTD = −0.0391 × 1M
    expect(screen.getByText("+USD 121.2K")).toBeInTheDocument(); // YTD = 0.1212 × 1M
  });

  it("omits the P&L amount line when no notional is set (% only)", () => {
    render(<PortfolioPnlStrip portfolio={portfolio()} {...RETURNS} />);
    expect(screen.getByText("+1.64%")).toBeInTheDocument();
    expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
  });
});
