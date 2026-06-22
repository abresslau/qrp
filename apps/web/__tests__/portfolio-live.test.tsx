import { render, screen, within } from "@testing-library/react";
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
  net_exposure: 0.6, gross_exposure: 1.0, long_exposure: 0.8, short_exposure: 0.2,
  weights: [
    { figi: "F1", ticker: "AAPL", name: "Apple", weight: 0.6 },
    { figi: "F2", ticker: "MSFT", name: "Microsoft", weight: 0.4 },
  ],
};

const PNL = {
  portfolio_id: 7, as_of_date: "2026-06-18", base_currency: "USD", notional: null, n_days: 7,
  daily_return: 0.0164, mtd_return: -0.0391, ytd_return: -0.0391,
  daily_pnl: null, mtd_pnl: null, ytd_pnl: null,
};

const COMP = {
  portfolio_id: 7, weights_as_of: "2026-06-05", as_of: "2026-06-19T14:30:00+00:00",
  freshness: "live", n_holdings: 2, n_priced: 2, total_weight: 1.0, net_weight: 0.6,
  holdings: [
    { figi: "F1", ticker: "AAPL", name: "Apple", sector: "Tech", industry: null, mic: "XNAS", country: "US", status: "active", weight: 0.6, currency: "USD", market_cap_usd: 1e9, volume: 1000, price: 110, live_return: 0.1, window_returns: {}, low_52w: null, high_52w: null, range_pct: null, freshness: "live" },
    { figi: "F2", ticker: "MSFT", name: "Microsoft", sector: "Tech", industry: null, mic: "XNAS", country: "US", status: "active", weight: 0.4, currency: "USD", market_cap_usd: 1e9, volume: 1000, price: 120, live_return: 0.05, window_returns: {}, low_52w: null, high_52w: null, range_pct: null, freshness: "live" },
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
      if (url.includes("/pnl")) return json(PNL);
      if (url.includes("/api/portfolios/7")) return json(PORTFOLIO);
      return json([]);
    }),
  );
}

beforeEach(() => stub());
afterEach(() => vi.unstubAllGlobals());

describe("PortfolioLive page", () => {
  it("renders the header P&L strip, the heat map, and the sector donut from one composition fetch", async () => {
    render(<PortfolioLive />);
    expect(await screen.findByText(/Long\/Short Book/)).toBeInTheDocument(); // header

    // Live P&L now sits in the header strip (no risk/exposure panel). Scope the assertions to the
    // strip itself — "Daily P&L" also appears as a grid column header, so a screen-wide getAllByText
    // would pass on the grid alone and never prove the header strip actually rendered.
    const strip = within(screen.getByTestId("pnl-strip"));
    expect(strip.getByText("Daily P&L")).toBeInTheDocument();
    expect(strip.getByText("MTD P&L")).toBeInTheDocument();
    expect(strip.getByText("YTD P&L")).toBeInTheDocument();
    // the removed risk/exposure stats are gone
    expect(screen.queryByText("L/S")).not.toBeInTheDocument();
    expect(screen.queryByText("Long")).not.toBeInTheDocument();

    // sector donut (in-slice + legend) + heat-map tiles
    expect(screen.getAllByText("Tech").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/AAPL/).length).toBeGreaterThan(0);

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.filter((u) => u.includes("/composition")).length).toBe(1);
  });

  it("a 503 surfaces the error banner, not a blank page", async () => {
    stub({ compOk: false });
    render(<PortfolioLive />);
    expect(await screen.findByText(/Couldn.t load live composition/)).toBeInTheDocument();
    expect(screen.getByText(/← Portfolio/)).toBeInTheDocument(); // page chrome intact
  });
});
