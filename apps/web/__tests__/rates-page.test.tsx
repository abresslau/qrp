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

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const body = url.includes("/spreads")
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
    expect(await screen.findByText("as of 2026-06-19")).toBeInTheDocument();
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes("/api/rates/curve?curve_set=glc&basis=nominal&rate_type=spot"))).toBe(true);
  });
});
