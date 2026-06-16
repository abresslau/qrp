import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/lib/api";
import { AnalyticsPanel } from "@/components/analytics-panel";

type LivePnl = Schemas["LivePnl"];

// A live-PnL payload with sane defaults; override per-test. The panel renders its live block
// only when `n_priced > 0`, badges by `freshness`, and labels `as_of` only when present.
function livePnl(over: Partial<LivePnl> = {}): LivePnl {
  return {
    portfolio_id: 5,
    weights_as_of: "2026-06-01",
    as_of: "2026-06-16T14:30:00+00:00",
    freshness: "live",
    n_constituents: 22,
    n_priced: 22,
    total_weight: 1,
    covered_weight: 1,
    live_return: 0.0049,
    live_return_normalized: 0.0049,
    notional: null,
    base_currency: "USD",
    pnl: null,
    constituents: [],
    ...over,
  } as LivePnl;
}

// Route fetch by URL: benchmarks -> [] (so no benchmark is selected and the analytics fetch
// never fires — the badge is independent of it), /live -> the supplied payload.
function stubFetch(live: LivePnl) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const ok = (body: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
      if (url.includes("/benchmarks")) return ok([]);
      if (url.includes("/live")) return ok(live);
      return ok({});
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("AnalyticsPanel live-PnL badge (QH.7 / AC4)", () => {
  it("renders a live badge with the emerald style and the normalized return", async () => {
    stubFetch(livePnl({ freshness: "live", live_return_normalized: 0.0049 }));
    render(<AnalyticsPanel pid="5" />);

    const badge = await screen.findByText("live");
    expect(badge.className).toContain("emerald"); // FRESH_STYLE.live
    expect(screen.getByText("+0.49%")).toBeInTheDocument();
    expect(screen.getByText(/22\/22 priced/)).toBeInTheDocument();
    expect(screen.getByText(/not stored/)).toBeInTheDocument();
    // Positive proof of the block marker + as-of label, so the gating / null-guard tests below
    // assert on real, present-when-expected text (not vacuously).
    expect(screen.getByText("Live PnL")).toBeInTheDocument();
    expect(screen.getByText(/as of/i)).toBeInTheDocument();
  });

  it("uses the amber style for a delayed mark", async () => {
    stubFetch(livePnl({ freshness: "delayed" }));
    render(<AnalyticsPanel pid="5" />);
    const badge = await screen.findByText("delayed");
    expect(badge.className).toContain("amber"); // FRESH_STYLE.delayed
  });

  it("falls back to the unavailable style for an unknown freshness value", async () => {
    stubFetch(livePnl({ freshness: "stale" as LivePnl["freshness"] }));
    render(<AnalyticsPanel pid="5" />);
    const badge = await screen.findByText("stale");
    expect(badge.className).toContain("bg-fg/5"); // FRESH_STYLE.unavailable fallback (?? )
  });

  it("hides the entire live block when nothing is priced (n_priced === 0)", async () => {
    stubFetch(livePnl({ freshness: "unavailable", n_priced: 0, live_return_normalized: null }));
    render(<AnalyticsPanel pid="5" />);
    // give the live fetch a chance to resolve, then assert the block never appears
    await screen.findByText(/Risk & return analytics|Risk &amp; return analytics/i);
    expect(screen.queryByText("Live PnL")).not.toBeInTheDocument();
  });

  it("omits the as-of label (and never shows Invalid Date) when as_of is null", async () => {
    stubFetch(livePnl({ as_of: null }));
    render(<AnalyticsPanel pid="5" />);
    await screen.findByText("live");
    expect(screen.queryByText(/as of/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
  });
});
