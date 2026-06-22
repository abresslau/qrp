import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import WeiPage from "@/app/monitor/wei/page";

const BOARD = [
  { sym_id: 1, name: "S&P 500", region: "Americas", country: "United States", currency: "USD", last: 5000, last_date: "2026-06-19", prev: 4950, chg: 50, chg_pct: 0.0101, d5: 0.005, mtd: 0.02, m1: 0.018, m3: 0.04, m6: 0.06, ytd: 0.1111, "1y": 0.15, "2y": 0.3, "3y": 0.45, "5y": 0.7, lo_52w: 4000, hi_52w: 5100, spark: [4500, 4800, 5000] },
  { sym_id: 2, name: "FTSE 100", region: "EMEA", country: "United Kingdom", currency: "GBP", last: 7250, last_date: "2026-06-18", prev: 8050, chg: -50, chg_pct: -0.0062, d5: -0.003, mtd: -0.01, m1: -0.005, m3: 0.02, m6: 0.03, ytd: 0.03, "1y": 0.08, "2y": 0.12, "3y": 0.18, "5y": 0.25, lo_52w: 7200, hi_52w: 8300, spark: [8200, 8100, 8000] },
  { sym_id: 3, name: "Nikkei 225", region: "Asia-Pacific", country: "Japan", currency: "JPY", last: 39000, last_date: "2026-06-19", prev: 38500, chg: 500, chg_pct: 0.013, d5: 0.01, mtd: 0.03, m1: 0.025, m3: 0.05, m6: 0.07, ytd: 0.05, "1y": 0.2, "2y": 0.35, "3y": 0.5, "5y": 0.9, lo_52w: 33000, hi_52w: 40000, spark: [37000, 38000, 39000] },
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

  it("shows the country and sorts by country then index name", async () => {
    // two US indices + one Brazil index, all in Americas, to prove country-then-name ordering
    const AMER = [
      { ...BOARD[0], sym_id: 21, name: "Zeta US Index", country: "United States" },
      { ...BOARD[0], sym_id: 22, name: "IBOVESPA", country: "Brazil" },
      { ...BOARD[0], sym_id: 23, name: "Alpha US Index", country: "United States" },
    ];
    stub(AMER);
    const { container } = render(<WeiPage />);
    await screen.findByText("Americas");
    expect(screen.getAllByText("United States", { selector: "td" }).length).toBe(2);
    expect(screen.getByText("Brazil", { selector: "td" })).toBeInTheDocument();
    const names = () =>
      [...container.querySelectorAll("tbody td:first-child")].map((td) => td.textContent?.replace(/●.*/, "").trim());
    // default sort IS country → Brazil before United States; within United States, index name asc
    expect(names()).toEqual(["IBOVESPA", "Alpha US Index", "Zeta US Index"]);
    // clicking Country toggles to descending (United States before Brazil; name asc within)
    fireEvent.click(screen.getByLabelText("Sort by Country"));
    expect(names()).toEqual(["Alpha US Index", "Zeta US Index", "IBOVESPA"]);
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
    expect(calls[0]).toBe("/api/sym/indices/board");
    // picking a past date backdates the board (server resolves last session ≤ date)
    const input = container.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2026-03-31" } });
    await waitFor(() => expect(calls.some((u) => u.includes("as_of_date=2026-03-31"))).toBe(true));
    // a Latest reset clears the param
    fireEvent.click(screen.getByText("Latest"));
    await waitFor(() => expect(calls[calls.length - 1]).toBe("/api/sym/indices/board"));
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

  it("sorts within each region — same-country rows fall back to index name; click a header to re-sort", async () => {
    const TWO = [
      { ...BOARD[0], sym_id: 11, name: "Zeta Index", region: "Americas", country: "United States", "1y": 0.05 },
      { ...BOARD[0], sym_id: 12, name: "Alpha Index", region: "Americas", country: "United States", "1y": 0.99 },
    ];
    stub(TWO);
    const { container } = render(<WeiPage />);
    await screen.findByText("Americas");
    const names = () => [...container.querySelectorAll("tbody td:first-child")].map((td) => td.textContent?.replace(/●.*/, "").trim());
    // default sort is country; both are United States, so they fall back to index name ascending
    expect(names()).toEqual(["Alpha Index", "Zeta Index"]);
    // first click on a numeric column sorts descending; a second click toggles to ascending
    fireEvent.click(screen.getByLabelText("Sort by 1Y"));
    expect(names()).toEqual(["Alpha Index", "Zeta Index"]); // 1Y desc: 0.99 then 0.05
    fireEvent.click(screen.getByLabelText("Sort by 1Y")); // toggle to ascending
    expect(names()).toEqual(["Zeta Index", "Alpha Index"]); // 1Y asc: 0.05 then 0.99
  });

  it("LIVE toggle fetches the live board, shows the live badge + per-row freshness marks", async () => {
    const LIVE = {
      as_of: "2026-06-22T15:30:00+00:00",
      freshness: "delayed",
      priced: 2,
      total: 3,
      rows: [
        { ...BOARD[0], last: 5050, chg_pct: 0.0234, freshness: "live", quote_time: "2026-06-22T15:30:00+00:00" },
        { ...BOARD[1], freshness: "delayed", quote_time: "2026-06-22T15:25:00+00:00" },
        { ...BOARD[2], freshness: "unavailable", quote_time: null },
      ],
    };
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        calls.push(url);
        const body = url.includes("/board/live") ? LIVE : BOARD;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      }),
    );
    render(<WeiPage />);
    await screen.findByText("Americas");
    expect(calls[0]).toBe("/api/sym/indices/board"); // EOD first

    fireEvent.click(screen.getByRole("button", { name: "LIVE" }));
    await waitFor(() => expect(calls.some((u) => u.includes("/board/live"))).toBe(true));
    // live badge: worst freshness + coverage
    expect(await screen.findByText(/LIVE · delayed · 2\/3 priced/)).toBeInTheDocument();
    // per-row marks: a delayed row + an unavailable row are flagged (the live row is not)
    expect(screen.getByTitle(/Delayed quote/)).toBeInTheDocument();
    expect(screen.getByTitle(/No live quote/)).toBeInTheDocument();
    // the live re-marked value renders (S&P 1D +2.34%)
    expect(screen.getByText("+2.34%")).toBeInTheDocument();

    // switching back to EOD restores the EOD board (no /board/live) + the as-of control
    fireEvent.click(screen.getByRole("button", { name: "EOD" }));
    await waitFor(() => expect(calls[calls.length - 1]).toBe("/api/sym/indices/board"));
    expect(document.querySelector('input[type="date"]')).toBeTruthy();
  });

  it("exposes a LIVE auto-refresh interval control (floored at 3s), hidden in EOD", async () => {
    const LIVE = { as_of: null, freshness: "delayed", priced: 1, total: 3, rows: BOARD.map((r) => ({ ...r, freshness: "delayed" })) };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(url.includes("/board/live") ? LIVE : BOARD) }),
      ),
    );
    render(<WeiPage />);
    await screen.findByText("Americas");
    // no auto control in EOD
    expect(screen.queryByLabelText("Auto-refresh interval in seconds")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "LIVE" }));
    const auto = await screen.findByLabelText("Auto-refresh interval in seconds");
    // a sub-3s value is floored to 3s in the cadence hint
    fireEvent.change(auto, { target: { value: "1" } });
    expect(screen.getByText(/\(3s\)/)).toBeInTheDocument();
    fireEvent.change(auto, { target: { value: "10" } });
    expect(screen.getByText(/\(10s\)/)).toBeInTheDocument();
    // back to EOD hides the control again
    fireEvent.click(screen.getByRole("button", { name: "EOD" }));
    await waitFor(() => expect(screen.queryByLabelText("Auto-refresh interval in seconds")).toBeNull());
  });

  it("shows an honest empty state when no index data", async () => {
    stub([]);
    render(<WeiPage />);
    expect(await screen.findByText(/No index level data yet/)).toBeInTheDocument();
    expect(screen.getByText(/sym msci-pull/)).toBeInTheDocument();
  });
});
