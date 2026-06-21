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
const colHeaders = (c: HTMLElement) => [...c.querySelectorAll("thead th")].slice(1).map((h) => codeOf(h.textContent));
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
afterEach(() => vi.unstubAllGlobals());

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
    expect(container.querySelectorAll("tbody tr").length).toBe(10); // 2 grids x (1 banner + 4 rows)
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
    // XXX stale -> ● on the shared column header (1) + its row header in each grid (2) = 3
    expect(screen.getAllByTitle(/stale — last observed 2026-06-01 \(17d\)/).length).toBe(3);
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

  it("shows an honest empty state when no FX data", async () => {
    stub({ as_of_date: "", currencies: [], meta: [], rows: [] });
    render(<FxMatrixPage />);
    expect(await screen.findByText(/No FX data yet/)).toBeInTheDocument();
    expect(screen.getByText(/sym fx load/)).toBeInTheDocument();
  });
});
