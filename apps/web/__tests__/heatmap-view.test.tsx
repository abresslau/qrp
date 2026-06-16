import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HeatmapView } from "@/components/heatmap-view";

const UNIVERSES = [{ universe_id: "u1", name: "S&P", members_resolved: 3 }];
const WINDOWS = [{ code: "YTD", label: "YTD" }];

function cell(over: Record<string, unknown> = {}) {
  return {
    ticker: "AAPL", name: "Apple", sector: "Tech", industry: null,
    market_cap_usd: 100, market_cap_lcy: null, currency: "USD", price: 110, ret: 0.1,
    ...over,
  };
}

const EOD = {
  universe_id: "u1", universe_name: "S&P", window: "YTD",
  members_resolved: 3, shown: 1, missing_mcap: 0, merged_share_classes: 0,
  cells: [cell()],
};
const LIVE = {
  universe_id: "u1", universe_name: "S&P", window: "LIVE",
  members_resolved: 3, shown: 3, missing_mcap: 0, merged_share_classes: 0,
  as_of: "2026-06-16T14:30:00+00:00", freshness: "delayed", priced: 2, total: 3,
  cells: [cell({ freshness: "live" }), cell({ ticker: "MSFT", name: "Microsoft", ret: -0.02, freshness: "delayed" }),
          cell({ ticker: "XYZ", name: "NoMap", ret: null, price: null, freshness: "unavailable" })],
};

// Route the heatmap fetch; the live behaviour is configurable per test.
function stub(opts: { liveHttpOk?: boolean } = {}) {
  const { liveHttpOk = true } = opts;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/heatmap/live"))
        return Promise.resolve({ ok: liveHttpOk, status: liveHttpOk ? 200 : 503, json: () => Promise.resolve(LIVE) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(EOD) });
    }),
  );
}

function windowSelect(): HTMLSelectElement {
  return screen.getAllByRole("combobox")[1] as HTMLSelectElement; // [0] = universe, [1] = window
}

beforeEach(() => stub());
afterEach(() => vi.unstubAllGlobals());

describe("HeatmapView LIVE mode (QH.9)", () => {
  it("selecting LIVE fetches the live endpoint and shows the freshness badge + coverage", async () => {
    render(<HeatmapView universes={UNIVERSES} windows={WINDOWS} defaultUniverse="u1" defaultWindow="YTD" />);
    await screen.findByText(/Heatmap/); // EOD mount render

    fireEvent.change(windowSelect(), { target: { value: "LIVE" } });

    // badge reflects the worst-priced rollup + honest coverage + "not stored"
    const badge = await screen.findByText("delayed");
    expect(badge.className).toContain("amber"); // LIVE_STYLE.delayed
    expect(screen.getByText(/2\/3 priced/)).toBeInTheDocument();
    expect(screen.getByText(/not stored/)).toBeInTheDocument();
    expect(screen.getByText(/as of/i)).toBeInTheDocument();

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes("/universes/u1/heatmap/live"))).toBe(true);
  });

  it("a 503 in LIVE mode surfaces the error (not a blank map) and keeps the selectors", async () => {
    stub({ liveHttpOk: false });
    render(<HeatmapView universes={UNIVERSES} windows={WINDOWS} defaultUniverse="u1" defaultWindow="YTD" />);
    await screen.findByText(/Heatmap/);

    fireEvent.change(windowSelect(), { target: { value: "LIVE" } });

    expect(await screen.findByText(/Failed to load heat map/)).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2); // selectors still present -> recoverable
  });
});
