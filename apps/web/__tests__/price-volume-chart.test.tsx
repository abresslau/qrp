import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PriceVolumeChart } from "@/components/price-volume-chart";

function bars(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    session_date: `2026-05-${String((i % 28) + 1).padStart(2, "0")}`,
    open: 99 + i,
    high: 101 + i,
    low: 98 + i,
    close: 100 + i,
    volume: 1_000_000 + i * 1000,
  }));
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(bars(40)) }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("PriceVolumeChart", () => {
  it("fetches history and renders a price line + volume bars", async () => {
    const { container } = render(<PriceVolumeChart figi="BBG1" currency="USD" />);
    await waitFor(() => expect(container.querySelector("svg")).toBeTruthy());

    const calls = fetchMock.mock.calls.map((c) => c[0] as string);
    expect(calls[0]).toContain("/api/sym/securities/BBG1/prices?days=365"); // 1Y default
    // a price line path + at least one volume bar rect
    const linePath = Array.from(container.querySelectorAll("path")).find((p) => (p.getAttribute("d") ?? "").startsWith("M"));
    expect(linePath).toBeTruthy();
    expect(container.querySelectorAll("rect").length).toBeGreaterThan(0);
  });

  it("switching the range refetches with the new day count", async () => {
    render(<PriceVolumeChart figi="BBG1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "1M" }));
    await waitFor(() => {
      const last = fetchMock.mock.calls.at(-1)?.[0] as string;
      expect(last).toContain("days=30");
    });
  });

  it("offers line/area/candle and renders candles when selected", async () => {
    const { container } = render(<PriceVolumeChart figi="BBG1" />);
    await waitFor(() => expect(container.querySelector("svg")).toBeTruthy());

    // default is line → exactly one M-path (the price line)
    const mPaths = () => Array.from(container.querySelectorAll("path")).filter((p) => (p.getAttribute("d") ?? "").startsWith("M"));
    expect(mPaths().length).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "candle" }));
    // candles are <g> wick+body groups, not a single line path → no M-path remains
    await waitFor(() => expect(mPaths().length).toBe(0));
    // bodies (rects) for ~40 bars + 40 volume bars → well over 40 rects
    expect(container.querySelectorAll("rect").length).toBeGreaterThan(40);

    fireEvent.click(screen.getByRole("button", { name: "area" }));
    // area = filled area path + the line path → 2 M-paths
    await waitFor(() => expect(mPaths().length).toBe(2));
  });

  it("YTD fetches ~13 months and clips the view to the latest year (no prior-year labels)", async () => {
    const dates = [
      "2025-11-03", "2025-11-17", "2025-12-01", "2025-12-15",
      "2026-01-05", "2026-01-19", "2026-02-02", "2026-02-16",
      "2026-03-02", "2026-03-16", "2026-04-06", "2026-04-20",
      "2026-05-04", "2026-05-18", "2026-06-01", "2026-06-15",
    ];
    const data = dates.map((d, i) => ({ session_date: d, open: 99 + i, high: 101 + i, low: 98 + i, close: 100 + i, volume: 1_000_000 }));
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(data) });

    render(<PriceVolumeChart figi="BBG1" />);
    await waitFor(() => expect(screen.getByText(/Nov '25/)).toBeInTheDocument()); // 1Y default shows 2025

    fireEvent.click(screen.getByRole("button", { name: "YTD" }));
    await waitFor(() => {
      const last = fetchMock.mock.calls.at(-1)?.[0] as string;
      expect(last).toContain("days=400");
    });
    // clipped to 2026 → no 2025 month labels remain
    await waitFor(() => expect(screen.queryByText(/'25/)).not.toBeInTheDocument());
    expect(screen.getByText(/Jan '26/)).toBeInTheDocument();
  });

  it("shows an honest empty state when there is no history", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve([]) });
    render(<PriceVolumeChart figi="BBGX" />);
    expect(await screen.findByText(/No price history/)).toBeInTheDocument();
  });
});
