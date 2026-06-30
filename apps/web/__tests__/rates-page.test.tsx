import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RatesPage from "@/app/rates/page";

const CURVE = {
  curve_set: "glc", basis: "nominal", rate_type: "spot", vintage: "latest",
  as_of_date: "2026-06-19",
  points: [{ tenor: 2, value: 4.0 }, { tenor: 10, value: 4.75 }, { tenor: 40, value: 5.4 }],
};
const SPREADS = [
  { key: "2s10s", label: "2s10s (nominal)", unit: "bp", value: 75.4, zscore: 0.39, percentile: 73,
    as_of_date: "2026-06-19", history: [{ as_of_date: "2026-06-01", value: 73.9 }, { as_of_date: "2026-06-19", value: 75.4 }] },
  { key: "be10y", label: "10y breakeven (RPI)", unit: "%", value: 3.19, zscore: -1.37, percentile: 13,
    as_of_date: "2026-06-19", history: [{ as_of_date: "2026-06-01", value: 3.3 }, { as_of_date: "2026-06-19", value: 3.19 }] },
];
// The country switcher + per-country series lists (added by the rates-sources story): the page fetches
// /countries once and /curve/series?country= on each country change. The snap-to-richest-nominal effect
// keys off `series`, so it MUST be an array — glc/nominal/spot is the richest entry here, which is what
// the default-curve test expects to load.
const COUNTRIES = [{ country: "GB", currency: "GBP", start_date: "2016-01-04", end_date: "2026-06-19" }];
const SERIES = [
  { country: "GB", curve_set: "glc", basis: "nominal", rate_type: "spot", days: 2600, start_date: "2016-01-04", end_date: "2026-06-19" },
  { country: "GB", curve_set: "glc", basis: "real", rate_type: "spot", days: 2600, start_date: "2016-01-04", end_date: "2026-06-19" },
  { country: "GB", curve_set: "ois", basis: "nominal", rate_type: "spot", days: 2000, start_date: "2018-01-02", end_date: "2026-06-19" },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const body = url.includes("/countries")
        ? COUNTRIES
        : url.includes("/curve/series")
          ? SERIES
          : url.includes("/spreads")
            ? SPREADS
            : url.includes("/spread/")
              ? { key: "2s10s", label: "2s10s (nominal)", unit: "bp", points: SPREADS[0].history }
              : CURVE; // /curve
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("RatesPage", () => {
  it("renders the spread monitors with value, z-score and percentile", async () => {
    stubFetch();
    render(<RatesPage />);
    expect(await screen.findByText("2s10s (nominal)")).toBeInTheDocument();
    expect(screen.getByText("+75.4 bp")).toBeInTheDocument(); // bp formatting
    expect(screen.getByText("3.19%")).toBeInTheDocument(); // breakeven is a % level, not bp
    expect(screen.getByText("z +0.39σ")).toBeInTheDocument();
  });

  it("fetches a spread's history when its card is clicked", async () => {
    stubFetch();
    render(<RatesPage />);
    fireEvent.click(await screen.findByText("2s10s (nominal)"));
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes("/api/rates/spread/2s10s"))).toBe(true);
  });

  it("loads the GLC nominal spot curve by default (as-of shown)", async () => {
    stubFetch();
    render(<RatesPage />);
    // the legend shows "Latest · <as_of_date>" (the rates-sources story replaced the old "as of …" copy)
    expect(await screen.findByText(/Latest · 2026-06-19/)).toBeInTheDocument();
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    // the curve fetch is now country-qualified (?country=GB&curve_set=…); match on params, not order
    expect(
      calls.some(
        (u) =>
          u.includes("/api/rates/curve?") &&
          u.includes("curve_set=glc") &&
          u.includes("basis=nominal") &&
          u.includes("rate_type=spot"),
      ),
    ).toBe(true);
  });
});
