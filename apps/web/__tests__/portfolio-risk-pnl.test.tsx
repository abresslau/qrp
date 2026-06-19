import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PortfolioRiskPnl } from "@/components/portfolio-risk-pnl";
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

const PNL_BASE = {
  portfolio_id: 7, as_of_date: "2026-06-18", base_currency: "USD", n_days: 7,
  daily_return: 0.0164, mtd_return: -0.0391, ytd_return: 0.1212,
};

function stub(pnl: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(pnl) })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("PortfolioRiskPnl", () => {
  it("shows exposures + L/S ratio and return-space P&L when no notional is set", async () => {
    stub({ ...PNL_BASE, notional: null, daily_pnl: null, mtd_pnl: null, ytd_pnl: null });
    render(<PortfolioRiskPnl pid="7" portfolio={portfolio()} dailyReturn={0.0164} />);

    expect(await screen.findByText("+1.64%")).toBeInTheDocument(); // live daily (from composition roll-up)
    expect(screen.getByText("80.0%")).toBeInTheDocument(); // long
    expect(screen.getByText("20.0%")).toBeInTheDocument(); // short
    expect(screen.getByText("+60.0%")).toBeInTheDocument(); // net (signed)
    expect(screen.getByText("100.0%")).toBeInTheDocument(); // gross
    expect(screen.getByText("4.00×")).toBeInTheDocument(); // L/S = 0.8 / 0.2
  });

  it("shows money when a notional is set", async () => {
    stub({ ...PNL_BASE, notional: 1_000_000, daily_pnl: 16_400, mtd_pnl: -39_100, ytd_pnl: 121_200 });
    render(<PortfolioRiskPnl pid="7" portfolio={portfolio({ notional: 1_000_000 })} dailyReturn={0.0164} />);
    expect(await screen.findByText("+16,400 USD")).toBeInTheDocument(); // notional × live daily
  });

  it("renders a dash for L/S ratio on a long-only book", async () => {
    stub({ ...PNL_BASE, notional: null, daily_pnl: null, mtd_pnl: null, ytd_pnl: null });
    render(
      <PortfolioRiskPnl pid="7" portfolio={portfolio({ long_exposure: 1.0, short_exposure: 0.0 })} dailyReturn={0.0} />,
    );
    await screen.findByText("Daily P&L");
    expect(screen.getByText("—")).toBeInTheDocument(); // L/S undefined when short == 0
  });
});
