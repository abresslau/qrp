import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PopulationMap } from "@/components/population-map";
import { WORLD_PATHS } from "@/lib/world-geo";

const UNIVERSES = [{ universe_id: "sp500", name: "S&P 500" }];

function layer(covered: number, total: number, status: string, latest = "2026-06-18") {
  return { covered, total, latest_date: latest, status };
}

const BY_COUNTRY = [
  {
    country_iso: "US", country: "United States", timezone: "America/New_York",
    members: 1791, active_members: 1790,
    prices: layer(1778, 1790, "partial"), returns: layer(1780, 1790, "partial"),
    fundamentals: layer(1761, 1790, "partial", "2026-06-16"),
  },
  {
    country_iso: "BR", country: "Brazil", timezone: "America/Sao_Paulo",
    members: 99, active_members: 99,
    prices: layer(99, 99, "ok"), returns: layer(99, 99, "ok"),
    fundamentals: layer(79, 99, "partial", "2026-06-12"),
  },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BY_COUNTRY) })),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("PopulationMap", () => {
  it("renders the world map and shades countries with tracked members", async () => {
    const { container } = render(<PopulationMap universes={UNIVERSES} />);
    // the summary line confirms the fetch resolved and both countries are in
    expect(await screen.findByText(/2 countries/)).toBeInTheDocument();
    expect(screen.getByText(/1,889 active/)).toBeInTheDocument(); // 1790 + 99

    const ocean = container.querySelector("svg rect")?.getAttribute("fill");
    const usPath = Array.from(container.querySelectorAll("path")).find(
      (p) => p.getAttribute("d") === WORLD_PATHS.US,
    );
    expect(usPath).toBeTruthy();
    // US has members → it is NOT painted the empty/ocean color (it carries a population shade)
    expect(usPath!.getAttribute("fill")).not.toBe(ocean);
  });

  it("hovering a country shows its per-layer breakdown + timezone", async () => {
    const { container } = render(<PopulationMap universes={UNIVERSES} />);
    await screen.findByText(/2 countries/);

    const usPath = Array.from(container.querySelectorAll("path")).find(
      (p) => p.getAttribute("d") === WORLD_PATHS.US,
    )!;
    fireEvent.mouseEnter(usPath);

    expect(await screen.findByText("United States")).toBeInTheDocument();
    expect(screen.getByText("1,790 active · 1,791 members")).toBeInTheDocument();
    expect(screen.getByText("1778/1790")).toBeInTheDocument(); // prices covered/total
    expect(screen.getByText(/America\/New_York/)).toBeInTheDocument(); // market timezone
  });

  it("switching to Coverage mode reveals the layer selector", async () => {
    render(<PopulationMap universes={UNIVERSES} />);
    await screen.findByText(/2 countries/);

    fireEvent.click(screen.getByRole("button", { name: "coverage" }));
    expect(screen.getByRole("button", { name: "prices" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "returns" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "fundamentals" })).toBeInTheDocument();
  });
});
