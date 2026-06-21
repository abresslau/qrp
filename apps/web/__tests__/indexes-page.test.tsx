import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import IndexesPage from "@/app/sym/indexes/page";

const INDEXES = [
  {
    sym_id: 2210, name: "MSCI World Net (USD)", currency: "USD", msci_code: "990100",
    variant: "NETR", n_levels: 6646, first_date: "2000-12-29", last_date: "2026-06-19",
    last_level: 11731.17,
  },
];
const LEVELS = {
  sym_id: 2210, name: "MSCI World Net (USD)", currency: "USD", msci_code: "990100",
  variant: "NETR", n_levels: 3, since_start_return: 3.715,
  trailing: { mtd: 0.011, qtd: 0.045, ytd: 0.082, "1y": 0.151, "2y": 0.205, "3y": 0.274, "5y": 0.663, "10y": 1.234 },
  series: [
    { date: "2000-12-29", level: 2487.61 },
    { date: "2013-06-19", level: 5000.0 },
    { date: "2026-06-19", level: 11731.17 },
  ],
};

function stub(opts: { empty?: boolean } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/levels"))
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(LEVELS) });
      return Promise.resolve({
        ok: true, status: 200, json: () => Promise.resolve(opts.empty ? [] : INDEXES),
      });
    }),
  );
}

beforeEach(() => stub());
afterEach(() => vi.unstubAllGlobals());

describe("Indexes page", () => {
  it("lists indexes and renders the selected series chart with stats", async () => {
    render(<IndexesPage />);
    // the index appears in the list (button) AND the detail header
    expect(await screen.findAllByText(/MSCI World Net \(USD\)/)).not.toHaveLength(0);
    expect(screen.getAllByText(/Net Return/).length).toBeGreaterThan(0); // variant label from NETR
    // the level chart renders (svg) once the series resolves
    expect(await screen.findByRole("img", { name: /Index level time series/i })).toBeInTheDocument();
    // latest level appears (the stat + the chart's top y-tick both format it)
    expect(screen.getAllByText("11,731.17").length).toBeGreaterThan(0);
    // since-start return formatted as a percent (2 decimals)
    expect(screen.getByText("+371.50%")).toBeInTheDocument();
    // trailing returns rendered (MTD/QTD/YTD/1Y/2Y/3Y/5Y/10Y from the series), 2 decimals.
    // MTD/QTD are stat-only labels (not range buttons), so unique; the rest are asserted by value.
    expect(screen.getByText("MTD")).toBeInTheDocument();
    expect(screen.getByText("QTD")).toBeInTheDocument();
    expect(screen.getByText("+1.10%")).toBeInTheDocument(); // mtd 0.011
    expect(screen.getByText("+8.20%")).toBeInTheDocument(); // ytd 0.082
    expect(screen.getByText("+66.30%")).toBeInTheDocument(); // 5y 0.663 cumulative
    expect(screen.getByText("+123.40%")).toBeInTheDocument(); // 10y 1.234 cumulative
    // multi-year cards also show the annualised (CAGR)
    expect(screen.getByText("+10.71% p.a.")).toBeInTheDocument(); // 5y: 1.663^(1/5)-1
    expect(screen.getByText("+8.37% p.a.")).toBeInTheDocument(); // 10y: 2.234^(1/10)-1
    // chart range selector present; switching range keeps the chart rendered
    fireEvent.click(screen.getByRole("button", { name: /^Max$/ }));
    fireEvent.click(screen.getByRole("button", { name: /^1Y$/ }));
    expect(screen.getByRole("img", { name: /Index level time series/i })).toBeInTheDocument();
  });

  it("renders the monthly returns calendar table (Year | Jan…Dec | YTD) below the chart", async () => {
    const DENSE = {
      ...LEVELS,
      series: [
        { date: "2023-12-31", level: 100 },
        { date: "2024-01-31", level: 110 },
        { date: "2024-02-29", level: 121 },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("/levels")
          ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(DENSE) })
          : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(INDEXES) }),
      ),
    );
    render(<IndexesPage />);
    expect(await screen.findByText("Monthly returns (%)")).toBeInTheDocument();
    expect(screen.getByText("Year")).toBeInTheDocument();
    expect(screen.getByText("Jan")).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();
    // Jan = 110/100−1 = +10.00, Feb = 121/110−1 = +10.00 (2 cells); YTD = 121/100−1 = +21.00
    expect(screen.getAllByText("+10.00")).toHaveLength(2);
    expect(screen.getByText("+21.00")).toBeInTheDocument();
  });

  it("defaults to the marquee MSCI World Net even when a non-MSCI index sorts first alphabetically", async () => {
    const MULTI = [
      { sym_id: 2064, name: "AEX", currency: "EUR", msci_code: null, variant: null, n_levels: 8585, first_date: "1992-10-12", last_date: "2026-06-05", last_level: 1041.1 },
      { sym_id: 2210, name: "MSCI World Net (USD)", currency: "USD", msci_code: "990100", variant: "NETR", n_levels: 6646, first_date: "2000-12-29", last_date: "2026-06-19", last_level: 15585.46 },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.includes("/levels"))
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(LEVELS) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MULTI) });
      }),
    );
    render(<IndexesPage />);
    // AEX is in the list, but the selected detail panel is the marquee MSCI World Net
    expect(await screen.findByText("AEX")).toBeInTheDocument();
    const detail = await screen.findByRole("img", { name: /Index level time series/i });
    const section = detail.closest("section")!;
    expect(section.textContent).toMatch(/MSCI World Net/);
    expect(section.textContent).not.toMatch(/AEX/);
  });

  it("shows an honest empty state with the msci-pull hint when no index data", async () => {
    stub({ empty: true });
    render(<IndexesPage />);
    expect(await screen.findByText(/No index level data yet/)).toBeInTheDocument();
    expect(screen.getByText(/sym msci-pull/)).toBeInTheDocument();
  });
});
