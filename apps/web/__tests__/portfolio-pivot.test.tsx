import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Composition } from "@/components/portfolio-heatmap";
import { PortfolioPivot } from "@/components/portfolio-pivot";

function holding(over: Record<string, unknown>) {
  return {
    figi: "F", ticker: "T", name: "n", sector: "Tech", industry: null, mic: "XNAS",
    country: "United States", status: "active", weight: 0.1, currency: "USD",
    market_cap_usd: 1e12, volume: 1_000_000, price: 100, live_return: 0,
    window_returns: { "1D": 0, "1M": 0, "3M": 0, "6M": 0 },
    low_52w: null, high_52w: null, range_pct: null, freshness: "live",
    ...over,
  };
}

const COMP: Composition = {
  portfolio_id: 1, weights_as_of: "2026-06-05", as_of: null, freshness: "live",
  n_holdings: 3, n_priced: 3, total_weight: 1.2, net_weight: 1.2,
  holdings: [
    holding({ figi: "F1", ticker: "AAPL", sector: "Tech", weight: 0.5, live_return: 0.1,
      window_returns: { "1D": 0.0123, "1M": 0.05, "3M": -0.02, "6M": null },
      low_52w: 50, high_52w: 150, range_pct: 0.75 }), // +4.17%; 75% up its 52w range
    holding({ figi: "F2", ticker: "INTC", sector: "Tech", weight: 0.4, live_return: -0.05 }), // −1.67%
    holding({ figi: "F3", ticker: "XOM", sector: "Energy", country: "United States", weight: 0.3, live_return: 0.01 }),
  ],
  sectors: [
    { sector: "Tech", weight: 0.9, n: 2, live_return: 0.0333 },
    { sector: "Energy", weight: 0.3, n: 1, live_return: 0.01 },
  ],
};

// A multi-country book so nested grouping has ≥2 DISTINCT inner siblings under one parent (and the
// same inner label — "United States" — repeats across parents, exercising the path-keyed rows).
const COMP_MULTI: Composition = {
  portfolio_id: 2, weights_as_of: "2026-06-05", as_of: null, freshness: "live",
  n_holdings: 4, n_priced: 4, total_weight: 1.0, net_weight: 1.0,
  holdings: [
    holding({ figi: "M1", ticker: "AAPL", sector: "Tech", country: "United States", weight: 0.4 }),
    holding({ figi: "M2", ticker: "SAP", sector: "Tech", country: "Germany", weight: 0.3 }),
    holding({ figi: "M3", ticker: "XOM", sector: "Energy", country: "United States", weight: 0.2 }),
    holding({ figi: "M4", ticker: "EQNR", sector: "Energy", country: "Norway", weight: 0.1 }),
  ],
  sectors: [
    { sector: "Tech", weight: 0.7, n: 2, live_return: 0 },
    { sector: "Energy", weight: 0.3, n: 2, live_return: 0 },
  ],
};

describe("PortfolioPivot", () => {
  it("renders FLAT (ungrouped) by default with a Sector column + Daily P&L grand total", () => {
    render(<PortfolioPivot data={COMP} />);
    // explorer-style + P&L column headers, now incl. a draggable Sector column (no orphan Return col)
    for (const h of ["Ticker", "Sector", "Country", "Exch", "Ccy", "Price", "52-week range", "Daily P&L", "MTD P&L", "YTD P&L", "Mkt cap", "Volume"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    expect(screen.queryByText("Return")).not.toBeInTheDocument();
    // FLAT by default: no group/subtotal rows — just header + grand total + the 3 holdings = 5 rows.
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(screen.queryByText(/· 2/)).not.toBeInTheDocument(); // no "Tech · 2" group subtotal row
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("XOM")).toBeInTheDocument();
    expect(screen.getAllByText("Tech").length).toBeGreaterThan(0); // Tech now shows in the Sector column
    // Daily P&L grand total = Σ weight·live_return (FX-hedged, no normalisation):
    // 0.5·0.1 + 0.4·(−0.05) + 0.3·0.01 = +3.30%
    expect(screen.getByText(/Total · 3 holdings/)).toBeInTheDocument();
    expect(screen.getByText("+3.30%")).toBeInTheDocument();
  });

  it("renders the trailing return columns then the Daily/MTD/YTD P&L contribution columns", () => {
    render(<PortfolioPivot data={COMP} />);
    // column order after Price: the four return windows, then the three P&L contribution columns
    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    const i = headers.indexOf("Price");
    expect(headers.slice(i, i + 10)).toEqual([
      "Price", "1D Chg", "1M Return", "3M Return", "6M Return", "52-week range",
      "Daily P&L", "MTD P&L", "YTD P&L", "Mkt cap",
    ]);
    // the header row carries all 18 columns (Ticker/Name/Country/Exch/Ccy/Sector + Wt + Price + 4 windows + 52W Range + 3 P&L + MktCap + Vol)
    const headerCells = screen.getAllByRole("row")[0].querySelectorAll("th");
    expect(headerCells).toHaveLength(18);
    // AAPL row, by position (Sector inserted after Ccy shifts the numeric columns +1):
    // ticker0 name1 country2 mic3 ccy4 sector5 weight6 price7 1D8 1M9 3M10 6M11 range12 daily13 mtd14
    const cells = Array.from(screen.getByText("AAPL").closest("tr")!.querySelectorAll("td")).map(
      (td) => td.textContent,
    );
    expect(cells[8]).toBe("+1.23%"); // 1D return
    expect(cells[9]).toBe("+5.00%"); // 1M return
    expect(cells[10]).toBe("-2.00%"); // 3M return
    expect(cells[11]).toBe("—"); // 6M null
    expect(cells[12]).not.toBe("—"); // 52W Range bar present (F1 has extremes)
    expect(cells[12]).toContain("150"); // shows the 52w high endpoint label
    expect(cells[13]).toBe("+5.00%"); // Daily P&L = 0.5 × live_return 0.1
    expect(cells[14]).toBe("—"); // MTD P&L (no MTD return on F1)
  });

  it("sorts holdings within a sector when a column header is clicked", () => {
    render(<PortfolioPivot data={COMP} />);
    const order = () => screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const idx = (rows: string[], t: string) => rows.findIndex((x) => x.includes(t));
    // default: largest position first within Tech → AAPL (0.5) before INTC (0.4)
    let rows = order();
    expect(idx(rows, "AAPL")).toBeLessThan(idx(rows, "INTC"));
    // click the active Wt header → toggles weight to ascending → INTC (0.4) before AAPL (0.5)
    fireEvent.click(screen.getByRole("button", { name: /Wt/ }));
    rows = order();
    expect(idx(rows, "INTC")).toBeLessThan(idx(rows, "AAPL"));
    // sort by 1D Chg ascending: INTC (0) below AAPL (+1.23%) flips when ascending
    fireEvent.click(screen.getByRole("button", { name: /1D Chg/ })); // desc first
    fireEvent.click(screen.getByRole("button", { name: /1D Chg/ })); // → asc
    rows = order();
    expect(idx(rows, "INTC")).toBeLessThan(idx(rows, "AAPL")); // 0 < 0.0123
  });

  it("adds a secondary sort with Ctrl/Cmd-click and breaks ties by it (within a sector)", () => {
    render(<PortfolioPivot data={COMP} />);
    const order = () => screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const idx = (rows: string[], t: string) => rows.findIndex((x) => x.includes(t));
    // Primary = Exch (both AAPL/INTC are XNAS -> a tie); secondary = Daily P&L breaks it.
    fireEvent.click(screen.getByRole("button", { name: /Exch/ })); // single sort by mic
    // Ctrl-click Daily P&L -> appended as secondary (desc): AAPL (0.5*0.1=+0.05) before INTC (0.4*-0.05=-0.02)
    fireEvent.click(screen.getByRole("button", { name: /Daily P&L/ }), { ctrlKey: true });
    expect(idx(order(), "AAPL")).toBeLessThan(idx(order(), "INTC"));
    // priority indicators appear only when >=2 sorts active: Exch shows "1", Daily P&L shows "2"
    expect(screen.getByRole("button", { name: /Exch/ }).textContent).toContain("1");
    expect(screen.getByRole("button", { name: /Daily P&L/ }).textContent).toContain("2");
    // Ctrl-click Daily P&L again -> toggles ONLY its direction to asc, keeping Exch primary:
    // INTC (-0.02) now before AAPL (+0.05)
    fireEvent.click(screen.getByRole("button", { name: /Daily P&L/ }), { metaKey: true });
    expect(idx(order(), "INTC")).toBeLessThan(idx(order(), "AAPL"));
    expect(screen.getByRole("button", { name: /Exch/ }).textContent).toContain("1"); // still primary
    expect(screen.getByRole("button", { name: /Daily P&L/ }).textContent).toContain("2"); // priority kept
  });

  it("a plain click collapses a multi-sort back to a single sort", () => {
    render(<PortfolioPivot data={COMP} />);
    const order = () => screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const idx = (rows: string[], t: string) => rows.findIndex((x) => x.includes(t));
    // build a 2-key sort
    fireEvent.click(screen.getByRole("button", { name: /Exch/ }));
    fireEvent.click(screen.getByRole("button", { name: /Daily P&L/ }), { ctrlKey: true });
    expect(screen.getByRole("button", { name: /Exch/ }).textContent).toContain("1");
    // plain click Ticker -> single sort asc, no priority numbers, AAPL before INTC (alphabetical)
    fireEvent.click(screen.getByRole("button", { name: /Ticker/ }));
    expect(idx(order(), "AAPL")).toBeLessThan(idx(order(), "INTC"));
    // single active sort shows no priority number on its header
    expect(screen.getByRole("button", { name: /Ticker/ }).textContent).not.toMatch(/\d/);
    // and the previously-secondary Daily P&L is no longer part of the sort (no arrow/number)
    expect(screen.getByRole("button", { name: /Daily P&L/ }).textContent?.trim()).toBe("Daily P&L");
  });

  // --- drag-to-reorder columns (Pointer Events) --------------------------------------------
  const th = (name: RegExp) => screen.getByRole("button", { name }).closest("th") as HTMLTableCellElement;
  const headerText = () => screen.getAllByRole("columnheader").map((h) => h.textContent ?? "");
  // press the source header, move past the 5px threshold onto the target, release on the target
  const dragColumn = (from: HTMLElement, to: HTMLElement) => {
    fireEvent.pointerDown(from, { button: 0, clientX: 0 });
    fireEvent.pointerMove(to, { clientX: 40 });
    fireEvent.pointerUp(to, { clientX: 40 });
  };

  it("renders the canonical column order on first render", () => {
    render(<PortfolioPivot data={COMP} />);
    const h = headerText();
    expect(h[0]).toContain("Ticker");
    expect(h[h.length - 1]).toContain("Volume");
  });

  it("reorders columns by dragging a header — header and body stay in sync", () => {
    render(<PortfolioPivot data={COMP} />);
    // drag Volume (last) and drop it onto Ticker (first) -> Volume becomes the first column
    dragColumn(th(/Volume/), th(/Ticker/));
    expect(headerText()[0]).toContain("Volume");
    // the stock-row cells follow the same order: AAPL row now leads with its volume cell (1.0M), ticker second
    const cells = Array.from(screen.getByText("AAPL").closest("tr")!.querySelectorAll("td")).map((td) => td.textContent);
    expect(cells[0]).toBe("1.0M"); // volume (1_000_000) now first
    expect(cells[1]).toContain("AAPL"); // ticker second
  });

  it("keeps aggregate totals under their column after a reorder", () => {
    render(<PortfolioPivot data={COMP} />);
    // move Wt to the end (drop on Volume); the grand-total weight % (fixture total_weight 1.2 -> 120.0%)
    // and the Daily P&L total (+3.30%) must still render after the reorder
    dragColumn(th(/Wt/), th(/Volume/));
    const totalRow = screen.getByText(/Total · 3 holdings/).closest("tr")!.textContent;
    expect(totalRow).toContain("120.0%"); // weight total still rendered (its cell followed the Wt column)
    expect(totalRow).toContain("+3.30%"); // Daily P&L total still rendered
  });

  it("still sorts on a plain header click after the drag machinery is added", () => {
    render(<PortfolioPivot data={COMP} />);
    const order = () => screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const idx = (rows: string[], t: string) => rows.findIndex((x) => x.includes(t));
    fireEvent.click(screen.getByRole("button", { name: /Ticker/ })); // sort by ticker asc
    expect(idx(order(), "AAPL")).toBeLessThan(idx(order(), "INTC"));
  });

  // --- group-by (drag a column header onto the drop zone that appears only while dragging) ------
  // The group-by zone has NO resting footprint — it appears once a groupable header starts dragging.
  const dragToZone = (from: HTMLElement) => {
    fireEvent.pointerDown(from, { button: 0, clientX: 0 });
    fireEvent.pointerMove(from, { clientX: 40 }); // cross the 5px threshold → the zone appears
    const z = document.querySelector("[data-groupby-zone]") as HTMLElement;
    fireEvent.pointerMove(z, { clientX: 40 });
    fireEvent.pointerUp(z, { clientX: 40 });
  };

  it("groups the grid when a column header is dragged onto the (drag-only) group-by zone", () => {
    render(<PortfolioPivot data={COMP} />);
    expect(document.querySelector("[data-groupby-zone]")).toBeNull(); // no resting zone row
    expect(screen.getAllByRole("row")).toHaveLength(5); // flat: header + total + 3 holdings
    dragToZone(th(/Sector/));
    // grouped by sector: + a "Tech · 2" and an "Energy · 1" subtotal row → 7 rows
    expect(screen.getAllByRole("row")).toHaveLength(7);
    expect(screen.getByText(/· 2/)).toBeInTheDocument(); // Tech group has 2 holdings
    expect(screen.getByRole("button", { name: /clear grouping/i })).toBeInTheDocument(); // ✕ chip in the breadcrumb
    // the grouped Sector column is now HIDDEN from the grid (shown in the breadcrumb instead)
    expect(screen.queryByRole("columnheader", { name: /Sector/ })).toBeNull();
  });

  it("returns to flat when the grouped header's ✕ is clicked", () => {
    render(<PortfolioPivot data={COMP} />);
    dragToZone(th(/Sector/));
    expect(screen.getAllByRole("row")).toHaveLength(7);
    fireEvent.click(screen.getByRole("button", { name: /clear grouping/i }));
    expect(screen.getAllByRole("row")).toHaveLength(5); // back to flat
  });

  // --- multi-level (nested) grouping: drag a 2nd column onto the strip to add a nesting level ----
  it("nests when a SECOND column header is dragged onto the zone (Sector → Country)", () => {
    render(<PortfolioPivot data={COMP} />);
    dragToZone(th(/Sector/)); // level 1: by sector → header+total+Tech·2+AAPL+INTC+Energy·1+XOM = 7 rows
    expect(screen.getAllByRole("row")).toHaveLength(7);
    dragToZone(th(/Country/)); // level 2: Country nested within Sector → +2 country subtotals = 9 rows
    expect(screen.getAllByRole("row")).toHaveLength(9);
    // 4 subtotal rows now: Tech·2 + (US·2 under Tech) + Energy·1 + (US·1 under Energy)
    expect(screen.getAllByText(/· 2/)).toHaveLength(2); // Tech subtree + United-States-under-Tech
    expect(screen.getAllByText(/· 1/)).toHaveLength(2); // Energy subtree + United-States-under-Energy
    // both grouped headers carry an ✕
    expect(screen.getAllByRole("button", { name: /clear grouping/i })).toHaveLength(2);
  });

  it("removes ONE nesting level when a breadcrumb chip's ✕ is clicked (outer level)", () => {
    render(<PortfolioPivot data={COMP} />);
    dragToZone(th(/Sector/));
    dragToZone(th(/Country/));
    expect(screen.getAllByRole("row")).toHaveLength(9);
    // grouped columns are hidden from the grid; ungroup lives in the breadcrumb chips.
    // the Sector chip's ✕ removes ONLY the sector level → single-level by Country
    fireEvent.click(screen.getByRole("button", { name: /clear grouping Sector/i }));
    // grouped by country alone: all 3 holdings are "United States" → 1 subtotal + 3 holdings + header + total = 6
    expect(screen.getAllByRole("row")).toHaveLength(6);
    expect(screen.getAllByRole("button", { name: /clear grouping/i })).toHaveLength(1); // only the Country chip now
    expect(screen.queryByRole("button", { name: /clear grouping Country/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /clear grouping Sector/i })).toBeNull();
    // Country (still grouped) is hidden; Sector (ungrouped) is visible again
    expect(screen.queryByRole("columnheader", { name: /Country/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /Sector/ })).not.toBeNull();
  });

  it("nests DISTINCT inner groups under a parent, ordered by gross weight desc (Sector → Country)", () => {
    render(<PortfolioPivot data={COMP_MULTI} />);
    dragToZone(th(/Sector/));
    dragToZone(th(/Country/));
    // 6 subtotal rows: Tech·2 → [US·1, Germany·1]; Energy·2 → [US·1, Norway·1]
    // + header + total + 4 holdings = 12 rows
    expect(screen.getAllByRole("row")).toHaveLength(12);
    // grouped columns hidden → these labels appear ONLY in subtotal rows (unambiguous)
    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const idx = (t: string) => rows.findIndex((x) => x.includes(t));
    // outer order: Tech subtree (0.7) before Energy subtree (0.3)
    expect(idx("Tech")).toBeLessThan(idx("Energy"));
    // INNER order within Tech: United States (0.4) before Germany (0.3) — proves per-level weight-desc sort
    expect(idx("United States")).toBeLessThan(idx("Germany"));
    expect(idx("Germany")).toBeLessThan(idx("Energy")); // Germany still inside the Tech subtree
    expect(idx("Norway")).toBeGreaterThan(idx("Energy")); // Norway nested under Energy
    // both distinct inner siblings rendered under Tech
    expect(screen.getByText("Germany")).toBeInTheDocument();
    expect(screen.getByText("Norway")).toBeInTheDocument();
  });

  it("removes the INNER nesting level when its breadcrumb chip ✕ is clicked", () => {
    render(<PortfolioPivot data={COMP} />);
    dragToZone(th(/Sector/));
    dragToZone(th(/Country/));
    expect(screen.getAllByRole("row")).toHaveLength(9);
    // the Country chip's ✕ removes ONLY the inner level → single-level by Sector
    fireEvent.click(screen.getByRole("button", { name: /clear grouping Country/i }));
    expect(screen.getAllByRole("row")).toHaveLength(7); // single-level by Sector (Tech·2 + Energy·1)
    expect(screen.queryByRole("button", { name: /clear grouping Sector/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /clear grouping Country/i })).toBeNull();
    // Sector (still grouped) hidden; Country (ungrouped) visible again
    expect(screen.queryByRole("columnheader", { name: /Sector/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /Country/ })).not.toBeNull();
  });

  it("shows an empty state with no holdings", () => {
    render(<PortfolioPivot data={{ ...COMP, holdings: [] }} />);
    expect(screen.getByText(/No holdings yet/)).toBeInTheDocument();
  });
});
