import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import WeiPage from "@/app/monitor/wei/page";

const BOARD = [
  { sym_id: 1, name: "S&P 500", region: "Americas", currency: "USD", last: 5000, last_date: "2026-06-19", prev: 4950, chg: 50, chg_pct: 0.0101, d5: 0.005, mtd: 0.02, m1: 0.018, m3: 0.04, m6: 0.06, ytd: 0.1111, "1y": 0.15, "2y": 0.3, "3y": 0.45, "5y": 0.7, lo_52w: 4000, hi_52w: 5100, spark: [4500, 4800, 5000] },
  { sym_id: 2, name: "FTSE 100", region: "EMEA", currency: "GBP", last: 7250, last_date: "2026-06-18", prev: 8050, chg: -50, chg_pct: -0.0062, d5: -0.003, mtd: -0.01, m1: -0.005, m3: 0.02, m6: 0.03, ytd: 0.03, "1y": 0.08, "2y": 0.12, "3y": 0.18, "5y": 0.25, lo_52w: 7200, hi_52w: 8300, spark: [8200, 8100, 8000] },
  { sym_id: 3, name: "Nikkei 225", region: "Asia-Pacific", currency: "JPY", last: 39000, last_date: "2026-06-19", prev: 38500, chg: 500, chg_pct: 0.013, d5: 0.01, mtd: 0.03, m1: 0.025, m3: 0.05, m6: 0.07, ytd: 0.05, "1y": 0.2, "2y": 0.35, "3y": 0.5, "5y": 0.9, lo_52w: 33000, hi_52w: 40000, spark: [37000, 38000, 39000] },
];

function stub(rows: unknown = BOARD) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(rows) })),
  );
}

beforeEach(() => stub());
afterEach(() => vi.unstubAllGlobals());

describe("WEI (world equity indices) page", () => {
  it("groups indices by region with last/chg/%chg/YTD and up-down colour", async () => {
    const { container } = render(<WeiPage />);
    // region section headers, in order
    expect(await screen.findByText("Americas")).toBeInTheDocument();
    expect(screen.getByText("EMEA")).toBeInTheDocument();
    expect(screen.getByText("Asia-Pacific")).toBeInTheDocument();
    // rows
    expect(screen.getByText("S&P 500")).toBeInTheDocument();
    expect(screen.getByText("FTSE 100")).toBeInTheDocument();
    expect(screen.getByText("Nikkei 225")).toBeInTheDocument();
    // up = emerald, down = rose (1-day % change)
    expect(screen.getByText("+1.01%").className).toMatch(/emerald/);
    expect(screen.getByText("-0.62%").className).toMatch(/rose/);
    // trailing-return columns render (MTD/3M/6M/YTD/1Y/2Y) — e.g. S&P 1Y +15.00%, 2Y +30.00%
    expect(screen.getByText("+15.00%")).toBeInTheDocument();
    expect(screen.getByText("+30.00%")).toBeInTheDocument();
    expect(screen.getByText("+11.11%")).toBeInTheDocument(); // YTD
    // a 52-week range bar per row (tooltip carries low/high + position), marker colour-coded by
    // proximity like portfolio-live: S&P near its high -> emerald, FTSE near its low -> rose
    expect(screen.getAllByTitle(/52w range/).length).toBe(3);
    expect(screen.getByTitle(/52w range 4,000\.00/).querySelector(".bg-emerald-500")).toBeTruthy();
    expect(screen.getByTitle(/52w range 7,200\.00/).querySelector(".bg-rose-500")).toBeTruthy();
    // a sparkline per row
    expect(container.querySelectorAll("svg").length).toBeGreaterThanOrEqual(3);
  });

  it("shows the EOD board date and marks rows behind the latest session as stale", async () => {
    render(<WeiPage />);
    await screen.findByText("Americas");
    expect(screen.getByText(/EOD · as of 2026-06-19/)).toBeInTheDocument();
    // FTSE 100's last_date (2026-06-18) lags the board max (2026-06-19) → a stale ● with a
    // holiday-aware tooltip naming the last close (date shown in the tooltip, not inline)
    expect(
      screen.getByTitle(/No session on 2026-06-19 .* showing the last close, 2026-06-18/),
    ).toBeInTheDocument();
  });

  it("re-fetches a backdated board when the as-of date changes, then resets to latest", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        calls.push(url);
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BOARD) });
      }),
    );
    const { container } = render(<WeiPage />);
    await screen.findByText("Americas");
    // initial load = latest (no as_of_date param)
    expect(calls[0]).toBe("/api/sym/indexes/board");
    // picking a past date backdates the board (server resolves last session ≤ date)
    const input = container.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2026-03-31" } });
    await waitFor(() => expect(calls.some((u) => u.includes("as_of_date=2026-03-31"))).toBe(true));
    // a Latest reset clears the param
    fireEvent.click(screen.getByText("Latest"));
    await waitFor(() => expect(calls[calls.length - 1]).toBe("/api/sym/indexes/board"));
  });

  it("defaults the date picker to the latest session (not empty, not today)", async () => {
    render(<WeiPage />);
    await screen.findByText("Americas");
    // the latest session across the board is 2026-06-19 (S&P / Nikkei); the picker shows it by default
    const input = document.querySelector('input[type="date"]') as HTMLInputElement;
    expect(input.value).toBe("2026-06-19");
    // no "Latest" reset shown while at the latest (not backdated)
    expect(screen.queryByText("Latest")).toBeNull();
  });

  it("sorts within each region — default by index name, click a header to re-sort", async () => {
    const TWO = [
      { ...BOARD[0], sym_id: 11, name: "Zeta Index", region: "Americas", "1y": 0.05 },
      { ...BOARD[0], sym_id: 12, name: "Alpha Index", region: "Americas", "1y": 0.99 },
    ];
    stub(TWO);
    const { container } = render(<WeiPage />);
    await screen.findByText("Americas");
    const names = () => [...container.querySelectorAll("tbody td:first-child")].map((td) => td.textContent?.replace(/●.*/, "").trim());
    // default = index name ascending
    expect(names()).toEqual(["Alpha Index", "Zeta Index"]);
    // sort by 1Y → numeric descending (Alpha 0.99 before Zeta 0.05 stays, so flip to check: click twice)
    fireEvent.click(screen.getByLabelText("Sort by 1Y"));
    expect(names()).toEqual(["Alpha Index", "Zeta Index"]); // 1Y desc: 0.99 then 0.05
    fireEvent.click(screen.getByLabelText("Sort by 1Y")); // toggle to ascending
    expect(names()).toEqual(["Zeta Index", "Alpha Index"]); // 1Y asc: 0.05 then 0.99
  });

  it("shows an honest empty state when no index data", async () => {
    stub([]);
    render(<WeiPage />);
    expect(await screen.findByText(/No index level data yet/)).toBeInTheDocument();
    expect(screen.getByText(/sym msci-pull/)).toBeInTheDocument();
  });
});
