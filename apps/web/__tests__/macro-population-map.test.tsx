import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MacroPopulationMap } from "@/components/macro-population-map";
import { WORLD_PATHS } from "@/lib/world-geo";

function s(series_id: string, geo: string, unit: string, latest: number) {
  return { series_id, source: "worldbank", name: "Population", geo, unit, frequency: "annual",
    category: "population", n_obs: 60, start_date: null, end_date: null, latest };
}

// US + China population & growth, plus an aggregate (Euro area, unmappable) and an off-topic series.
const SERIES = [
  s("WB:SP.POP.TOTL:US", "United States", "millions", 340.1),
  s("WB:SP.POP.GROW:US", "United States", "% per year", 0.98),
  s("WB:SP.POP.TOTL:CHN", "China", "millions", 1408.9),
  s("WB:SP.POP.GROW:CHN", "China", "% per year", -0.12),
  s("WB:SP.POP.TOTL:EMU", "Euro area", "millions", 351.1), // aggregate → not shaded
  { ...s("WB:NY.GDP.MKTP.CD:US", "United States", "USD", 27), category: "gdp" }, // not population
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SERIES) })),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("MacroPopulationMap", () => {
  it("shades only mapped population countries (aggregates/other categories excluded)", async () => {
    const { container } = render(<MacroPopulationMap />);
    expect(await screen.findByText(/2 countries/)).toBeInTheDocument(); // US + China, NOT Euro area

    const ocean = container.querySelector("svg rect")?.getAttribute("fill");
    const usFill = Array.from(container.querySelectorAll("path"))
      .find((p) => p.getAttribute("d") === WORLD_PATHS.US)
      ?.getAttribute("fill");
    expect(usFill).toBeTruthy();
    expect(usFill).not.toBe(ocean); // US carries a population shade
  });

  it("hovering a country shows population + growth", async () => {
    const { container } = render(<MacroPopulationMap />);
    await screen.findByText(/2 countries/);

    const us = Array.from(container.querySelectorAll("path")).find(
      (p) => p.getAttribute("d") === WORLD_PATHS.US,
    )!;
    fireEvent.mouseEnter(us);

    expect(await screen.findByText("United States")).toBeInTheDocument();
    expect(screen.getByText("340.1M")).toBeInTheDocument();
    expect(screen.getByText("+0.98%/yr")).toBeInTheDocument();
  });

  it("has a Total/Growth metric toggle", async () => {
    render(<MacroPopulationMap />);
    await screen.findByText(/2 countries/);
    expect(screen.getByRole("button", { name: "Total population" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Growth" }));
    expect(screen.getByText(/shrinking/)).toBeInTheDocument(); // growth legend
  });
});
