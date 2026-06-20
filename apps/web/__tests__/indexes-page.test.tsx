import { render, screen } from "@testing-library/react";
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
  trailing: { ytd: 0.082, "1y": 0.151, "3y": 0.274, "5y": 0.663 },
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
    // since-start return formatted as a percent
    expect(screen.getByText("+371.5%")).toBeInTheDocument();
    // trailing returns rendered (YTD / 1Y / 3Y / 5Y from the series)
    expect(screen.getByText("YTD")).toBeInTheDocument();
    expect(screen.getByText("+8.2%")).toBeInTheDocument(); // ytd 0.082
    expect(screen.getByText("+66.3%")).toBeInTheDocument(); // 5y 0.663
  });

  it("shows an honest empty state with the msci-pull hint when no index data", async () => {
    stub({ empty: true });
    render(<IndexesPage />);
    expect(await screen.findByText(/No index level data yet/)).toBeInTheDocument();
    expect(screen.getByText(/sym msci-pull/)).toBeInTheDocument();
  });
});
