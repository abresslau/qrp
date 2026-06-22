import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FxMatrixPage from "@/app/monitor/fx/page";

// ranks: EUR 10 < USD 50 < JPY 100 < XXX (unranked). rows are keyed by BASE; cell = quote per base.
const C = (rate: number | null, chg: number | null, stale: boolean, pair: string) => ({ rate, chg, stale, pair });
const MATRIX = {
  as_of_date: "2026-06-18",
  currencies: ["EUR", "JPY", "XXX", "USD"], // warehouse order (USD last)
  meta: [
    { currency: "EUR", status: "ok", observed_date: "2026-06-18", days_stale: 0, quote_rank: 10 },
    { currency: "JPY", status: "ok", observed_date: "2026-06-18", days_stale: 0, quote_rank: 100 },
    { currency: "XXX", status: "stale", observed_date: "2026-06-01", days_stale: 17, quote_rank: 10000 },
    { currency: "USD", status: "ok", observed_date: "2026-06-18", days_stale: 0, quote_rank: 50 },
  ],
  // rows[base].cells[quoteIdx] = quote per 1 base, in `currencies` order [EUR, JPY, XXX, USD]
  rows: [
    { base: "EUR", cells: [C(1, 0, false, "EUR/EUR"), C(168.48, 0.017, false, "EUR/JPY"), C(null, null, true, "EUR/XXX"), C(1.087, 0.011, false, "EUR/USD")] },
    { base: "JPY", cells: [C(0.00594, -0.017, false, "EUR/JPY"), C(1, 0, false, "JPY/JPY"), C(null, null, true, "JPY/XXX"), C(0.00645, -0.013, false, "USD/JPY")] },
    { base: "XXX", cells: [C(null, null, true, "EUR/XXX"), C(null, null, true, "JPY/XXX"), C(1, 0, false, "XXX/XXX"), C(null, null, true, "USD/XXX")] },
    { base: "USD", cells: [C(0.92, -0.011, false, "EUR/USD"), C(155, 0.013, false, "USD/JPY"), C(null, null, true, "USD/XXX"), C(1, 0, false, "USD/USD")] },
  ],
};

function stub(body: unknown = MATRIX) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })),
  );
}
// headers carry a flag emoji + ● marker; pull out just the 3-letter code
const codeOf = (s: string | null) => (s ?? "").replace(/[^A-Z]/g, "");
// each card has its own <thead>; column headers are the last header row's cells after the corner th
const colHeaders = (c: HTMLElement) => {
  const rows = [...c.querySelectorAll("thead")[0].querySelectorAll("tr")];
  const headerRow = rows[rows.length - 1];
  return [...headerRow.querySelectorAll("th")].slice(1).map((h) => codeOf(h.textContent));
};
const rowHeaders = (c: HTMLElement, grid = 0) =>
  [...c.querySelectorAll("tbody")[grid].querySelectorAll("tr")].filter((r) => r.querySelector("td")).map((r) => codeOf(r.querySelector("th")!.textContent));
// the cell at (rowCcy, colCcy) in grid index (0 = rate, 1 = % change)
function cellAt(c: HTMLElement, rowCcy: string, colCcy: string, grid = 0): HTMLElement {
  const tbody = c.querySelectorAll("tbody")[grid];
  const row = [...tbody.querySelectorAll("tr")].find(
    (r) => r.querySelector("td") && codeOf(r.querySelector("th")!.textContent) === rowCcy,
  )!;
  const ci = colHeaders(c).indexOf(colCcy);
  return row.querySelectorAll("td")[ci] as HTMLElement;
}
// parse an element's inline backgroundColor "rgb(r, g, b)" → [r, g, b]
const rgbOf = (el: HTMLElement): [number, number, number] =>
  (el.style.backgroundColor.match(/\d+/g) ?? []).map(Number) as [number, number, number];

beforeEach(() => stub());
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear(); // the saved drag order persists in localStorage — don't leak across tests
});

// a row header <th> by currency code, in the given grid (card)
const rowTh = (c: HTMLElement, ccy: string, grid = 0): HTMLElement =>
  [...c.querySelectorAll("tbody")[grid].querySelectorAll("tr")]
    .map((r) => r.querySelector("th") as HTMLElement)
    .find((th) => codeOf(th.textContent) === ccy)!;

describe("FX cross-rate matrix page", () => {
  it("default sorting: base USD, row last / column first (USD bottom row, USD first column)", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    expect(colHeaders(container)).toEqual(["USD", "EUR", "JPY", "XXX"]); // USD first column
    expect(rowHeaders(container)).toEqual(["EUR", "JPY", "XXX", "USD"]); // USD last row; rest in order
  });

  it("column = base by default: USD-row/EUR-col = EUR/USD = 1.0870 (and reads in 2dp/4dp)", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    // USD row, EUR col: base=EUR, quote=USD → USD per EUR = EUR/USD = 1.0870
    expect(cellAt(container, "USD", "EUR").textContent).toBe("1.0870");
    // +1.1% → green-tinted fill (green channel dominates); -1.1% → red-tinted (red dominates)
    const up = rgbOf(cellAt(container, "USD", "EUR"));
    expect(up[1]).toBeGreaterThan(up[0]); // g > r
    const down = rgbOf(cellAt(container, "EUR", "USD")); // EUR-row/USD-col = USD/EUR, -1.1%
    expect(down[0]).toBeGreaterThan(down[1]); // r > g
    // JPY row, USD col: base=USD, quote=JPY → JPY per USD = USD/JPY = 155.00 (2dp)
    expect(cellAt(container, "JPY", "USD").textContent).toBe("155.00");
    // diagonal USD/USD is "—" + shaded
    expect(cellAt(container, "USD", "USD").textContent).toBe("—");
    expect(cellAt(container, "USD", "USD").className).toMatch(/bg-fg/);
    expect(container.querySelectorAll("tbody tr").length).toBe(8); // 2 cards x 4 currency rows
  });

  it("shows a country flag image beside each currency (2nd column + column header)", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    // USD column header carries the US flag image (bundled SVG, same-origin)
    const usdCol = [...container.querySelectorAll("thead th")].slice(1).find((h) => codeOf(h.textContent) === "USD");
    expect(usdCol!.querySelector("img")?.getAttribute("src")).toBe("/flags/us.svg");
    // EUR row: the 2nd header cell (flag column) holds the EU flag image
    const eurRow = [...container.querySelectorAll("tbody tr")].find(
      (r) => r.querySelector("td") && codeOf(r.querySelector("th")!.textContent) === "EUR",
    )!;
    expect(eurRow.querySelectorAll("th")[1].querySelector("img")?.getAttribute("src")).toBe("/flags/eu.svg");
  });

  it("shows a % change on day legend (conditional-formatting key) with banded swatches", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    expect(screen.getByText("% change on day")).toBeInTheDocument();
    // the seven FXC bands, including the neutral ±0.05% band
    expect(screen.getByText("±0.05%")).toBeInTheDocument();
    expect(screen.getByText("≥ 2.5%")).toBeInTheDocument();
    expect(screen.getByText("≤ −2.5%")).toBeInTheDocument();
    // the strongest +band swatch is green-dominant, the strongest −band is red-dominant
    const strongUp = rgbOf(screen.getByText("≥ 2.5%"));
    expect(strongUp[1]).toBeGreaterThan(strongUp[0]);
    const strongDown = rgbOf(screen.getByText("≤ −2.5%"));
    expect(strongDown[0]).toBeGreaterThan(strongDown[1]);
  });

  it("shows a second Daily % change grid", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    expect(screen.getByText("Spot rate")).toBeInTheDocument();
    expect(screen.getByText("Spot · daily % change")).toBeInTheDocument();
    expect(cellAt(container, "USD", "EUR", 1).textContent).toBe("+1.10%"); // EUR/USD daily move, % grid
  });

  it("Sorting control repositions the base currency on each axis", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    const sorting = container.querySelectorAll("select")[1] as HTMLSelectElement; // Base currency is 1st
    // both base-first → USD leads both axes
    fireEvent.change(sorting, { target: { value: "ff" } });
    expect(colHeaders(container)).toEqual(["USD", "EUR", "JPY", "XXX"]);
    expect(rowHeaders(container)).toEqual(["USD", "EUR", "JPY", "XXX"]);
    // both base-last → USD trails both axes
    fireEvent.change(sorting, { target: { value: "ll" } });
    expect(colHeaders(container)).toEqual(["EUR", "JPY", "XXX", "USD"]);
    expect(rowHeaders(container)).toEqual(["EUR", "JPY", "XXX", "USD"]);
  });

  it("Base currency control re-anchors which currency is positioned", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    const baseSel = container.querySelectorAll("select")[0] as HTMLSelectElement;
    fireEvent.change(baseSel, { target: { value: "EUR" } }); // default sorting lf (row last / col first)
    expect(colHeaders(container)[0]).toBe("EUR"); // EUR now the first column
    expect(rowHeaders(container).at(-1)).toBe("EUR"); // EUR now the last (bottom) row
  });

  it("Base axis control flips the cross orientation (columns ⟷ rows)", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    expect(cellAt(container, "USD", "EUR").textContent).toBe("1.0870"); // columns=base: USD/EUR-col → EUR/USD
    const axisSel = container.querySelectorAll("select")[2] as HTMLSelectElement; // 3rd select
    fireEvent.change(axisSel, { target: { value: "rows" } });
    expect(cellAt(container, "USD", "EUR").textContent).toBe("0.9200"); // rows=base → EUR per 1 USD
  });

  it("marks a stale currency and blanks its cells (never a fabricated cross)", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    // XXX stale -> ● on each card's column header (2) + its row header in each card (2) = 4
    expect(screen.getAllByTitle(/stale — last observed 2026-06-01 \(17d\)/).length).toBe(4);
    // a cell touching XXX has no rate; the tooltip labels the displayed direction
    expect(cellAt(container, "USD", "XXX").textContent).toBe("—");
    expect(cellAt(container, "USD", "XXX").getAttribute("title")).toMatch(/no fresh rate for XXX\/USD/);
  });

  it("backdates on date change and resets to latest", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        calls.push(url);
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MATRIX) });
      }),
    );
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    expect(calls[0]).toBe("/api/sym/fx/matrix");
    fireEvent.change(container.querySelector('input[type="date"]') as HTMLInputElement, { target: { value: "2026-03-31" } });
    await waitFor(() => expect(calls.some((u) => u.includes("as_of_date=2026-03-31"))).toBe(true));
    fireEvent.click(screen.getByText("Latest"));
    await waitFor(() => expect(calls[calls.length - 1]).toBe("/api/sym/fx/matrix"));
  });

  it("drag-reorders a currency on both axes and persists the order", async () => {
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    // default rows: EUR, JPY, XXX, USD (USD pinned last by sorting)
    expect(rowHeaders(container)).toEqual(["EUR", "JPY", "XXX", "USD"]);
    // drag EUR onto JPY → EUR moves after JPY in the shared sequence
    const store: Record<string, string> = {};
    const dt = {
      dataTransfer: { setData: (k: string, v: string) => void (store[k] = v), getData: (k: string) => store[k] ?? "", effectAllowed: "" },
    };
    fireEvent.dragStart(rowTh(container, "EUR"), dt);
    fireEvent.dragOver(rowTh(container, "JPY"), dt);
    fireEvent.drop(rowTh(container, "JPY"), dt);
    // both axes reflect the new order (USD still pinned by sorting; columns put USD first)
    expect(rowHeaders(container)).toEqual(["JPY", "EUR", "XXX", "USD"]);
    expect(rowHeaders(container, 1)).toEqual(["JPY", "EUR", "XXX", "USD"]); // the % card matches
    expect(colHeaders(container)).toEqual(["USD", "JPY", "EUR", "XXX"]);
    // persisted to localStorage
    expect(JSON.parse(localStorage.getItem("qrp.fx.order")!)).toEqual(["JPY", "EUR", "XXX", "USD"]);
    // a Reset order control appears and restores the default
    fireEvent.click(screen.getByText("Reset order"));
    expect(rowHeaders(container)).toEqual(["EUR", "JPY", "XXX", "USD"]);
    expect(localStorage.getItem("qrp.fx.order")).toBeNull();
  });

  it("persists base currency / sorting / base axis and restores them on load", async () => {
    // changing a control writes to localStorage
    const { container, unmount } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    fireEvent.change(container.querySelectorAll("select")[2], { target: { value: "rows" } }); // Base axis
    fireEvent.change(container.querySelectorAll("select")[1], { target: { value: "ff" } }); // Sorting
    fireEvent.change(container.querySelectorAll("select")[0], { target: { value: "EUR" } }); // Base currency
    expect(localStorage.getItem("qrp.fx.baseAxis")).toBe("rows");
    expect(localStorage.getItem("qrp.fx.sorting")).toBe("ff");
    expect(localStorage.getItem("qrp.fx.baseCcy")).toBe("EUR");
    unmount();
    // a fresh mount (≈ F5) restores them
    const { container: c2 } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    await waitFor(() => expect(colHeaders(c2)[0]).toBe("EUR")); // base EUR + sorting ff → EUR leads both axes
    expect(rowHeaders(c2)[0]).toBe("EUR");
    expect(cellAt(c2, "USD", "EUR").textContent).toBe("0.9200"); // base axis = rows → EUR per 1 USD
  });

  it("restores a previously saved drag order on load", async () => {
    localStorage.setItem("qrp.fx.order", JSON.stringify(["JPY", "EUR", "XXX", "USD"]));
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    // the saved order is applied by the reconcile effect after data loads
    await waitFor(() => expect(rowHeaders(container)).toEqual(["JPY", "EUR", "XXX", "USD"]));
  });

  it("shows an honest empty state when no FX data", async () => {
    stub({ as_of_date: "", currencies: [], meta: [], rows: [] });
    render(<FxMatrixPage />);
    expect(await screen.findByText(/No FX data yet/)).toBeInTheDocument();
    expect(screen.getByText(/sym fx load/)).toBeInTheDocument();
  });

  // LIVE matrix body (Story fx-matrix-live): same grid shape + per-currency freshness/quote_time and a
  // rollup; no as_of_date. EUR/USD read live (no marker), JPY delayed, XXX unavailable (3/4 priced).
  const LIVE_MATRIX = {
    currencies: ["EUR", "JPY", "XXX", "USD"],
    meta: [
      { currency: "EUR", status: "ok", observed_date: "2026-06-18", days_stale: 0, quote_rank: 10, freshness: "live", quote_time: "2026-06-22T12:00:00Z" },
      { currency: "JPY", status: "ok", observed_date: "2026-06-18", days_stale: 0, quote_rank: 100, freshness: "delayed", quote_time: "2026-06-22T11:59:00Z" },
      { currency: "XXX", status: "stale", observed_date: "2026-06-01", days_stale: 17, quote_rank: 10000, freshness: "unavailable", quote_time: null },
      { currency: "USD", status: "ok", observed_date: "2026-06-18", days_stale: 0, quote_rank: 50, freshness: "live", quote_time: null },
    ],
    rows: MATRIX.rows,
    as_of: "2026-06-22T12:00:00Z",
    freshness: "delayed",
    priced: 3,
    total: 4,
  };

  it("LIVE toggle fetches /fx/matrix/live, shows the live badge + per-currency freshness, swaps the as-of control for auto-refresh", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        calls.push(url);
        const body = url.includes("/fx/matrix/live") ? LIVE_MATRIX : MATRIX;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      }),
    );
    const { container } = render(<FxMatrixPage />);
    await screen.findByText("FX cross-rate matrix");
    // EOD (default): the as-of date control is present; no auto-refresh control
    expect(container.querySelector('input[type="date"]')).not.toBeNull();
    expect(screen.queryByLabelText("Auto-refresh interval in seconds")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "LIVE" }));
    await waitFor(() => expect(calls.some((u) => u.includes("/fx/matrix/live"))).toBe(true));

    // live badge with worst freshness + coverage
    await screen.findByText(/LIVE · delayed · 3\/4 priced/);
    // per-currency freshness markers: JPY delayed (amber) + XXX unavailable (muted), across both cards
    expect(screen.getAllByTitle(/delayed quote/).length).toBeGreaterThan(0);
    expect(screen.getAllByTitle(/no live quote — showing the EOD rate/).length).toBeGreaterThan(0);
    // controls swap: auto-refresh appears, the as-of date control is gone (LIVE is "now")
    expect(screen.getByLabelText("Auto-refresh interval in seconds")).toBeInTheDocument();
    expect(container.querySelector('input[type="date"]')).toBeNull();

    // back to EOD restores the as-of control + drops the live badge
    fireEvent.click(screen.getByRole("button", { name: "EOD" }));
    await waitFor(() => expect(container.querySelector('input[type="date"]')).not.toBeNull());
    expect(screen.queryByText(/LIVE · delayed/)).toBeNull();
  });
});
