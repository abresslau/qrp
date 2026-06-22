import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ExplorerPage from "@/app/sym/explorer/page";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// Adidas (Xetra) — region GR / venue GY / FactSet DE; ZZZ — all codes null (fallback to bare).
const SECURITIES = {
  total: 2,
  limit: 50,
  offset: 0,
  rows: [
    {
      figi: "F1", ticker: "ADS", name: "Adidas AG", mic: "XETR", currency: "EUR", status: "active",
      price: 230, session_date: "2026-06-18", volume: 1e6, market_cap_usd: 4e10,
      country: "Germany", country_iso: "DE", sector: "Consumer Discretionary",
      exch_code: "GR", bbg_exchange_code: "GY",
    },
    {
      figi: "F2", ticker: "ZZZ", name: "No Codes Co", mic: null, currency: "USD", status: "active",
      price: null, session_date: null, volume: null, market_cap_usd: null,
      country: null, country_iso: null, sector: null,
      exch_code: null, bbg_exchange_code: null,
    },
  ],
};

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const body = url.includes("/universes") ? [] : SECURITIES;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }),
  );
}

beforeEach(() => {
  localStorage.clear(); // the convention pref persists in localStorage — don't leak across tests
  stub();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("Explorer — qualified ticker", () => {
  it("shows the Bloomberg Region form by default (ADS GR) and falls back to bare for a null-code row", async () => {
    render(<ExplorerPage />);
    expect(await screen.findByText("ADS GR")).toBeInTheDocument(); // default = bbg-region
    expect(screen.getByText("ZZZ")).toBeInTheDocument(); // null region code → bare ticker
    expect(screen.queryByText("ADS")).not.toBeInTheDocument(); // never the bare ADS when a code exists
  });

  it("the convention selector switches all forms (Region → Exchange → FactSet → Plain)", async () => {
    render(<ExplorerPage />);
    await screen.findByText("ADS GR");
    const sel = screen.getByLabelText("Ticker convention") as HTMLSelectElement;

    fireEvent.change(sel, { target: { value: "bbg-exchange" } });
    expect(await screen.findByText("ADS GY")).toBeInTheDocument();
    expect(screen.getByText("ZZZ")).toBeInTheDocument(); // null venue → bare

    fireEvent.change(sel, { target: { value: "factset" } });
    expect(await screen.findByText("ADS-DE")).toBeInTheDocument();

    fireEvent.change(sel, { target: { value: "plain" } });
    expect(await screen.findByText("ADS")).toBeInTheDocument(); // bare ticker
  });

  it("lists all three forms in the ticker tooltip", async () => {
    render(<ExplorerPage />);
    const link = (await screen.findByText("ADS GR")) as HTMLAnchorElement;
    const title = link.getAttribute("title") ?? "";
    expect(title).toContain("ADS GR");
    expect(title).toContain("ADS GY");
    expect(title).toContain("ADS-DE");
  });

  it("recovers from a stale/invalid stored convention (no blank select)", async () => {
    localStorage.setItem("qrp.ticker.convention", "garbage-value");
    render(<ExplorerPage />);
    await screen.findByText("ADS GR"); // falls back to the default, renders the region form
    const sel = screen.getByLabelText("Ticker convention") as HTMLSelectElement;
    expect(sel.value).toBe("bbg-region"); // controlled select has a valid selected option
  });
});
