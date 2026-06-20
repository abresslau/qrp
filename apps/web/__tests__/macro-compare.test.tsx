import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MacroCompare } from "@/components/macro-compare";

// two same-(name, unit) inflation series across countries -> one comparable group
const SERIES = [
  { series_id: "WB:CPI:USA", name: "CPI YoY", unit: "%", geo: "United States", latest: 3.1, category: "inflation" },
  { series_id: "WB:CPI:DEU", name: "CPI YoY", unit: "%", geo: "Germany", latest: 5.9, category: "inflation" },
] as unknown as Parameters<typeof MacroCompare>[0]["series"];

const DETAIL: Record<string, unknown> = {
  "WB:CPI:USA": { series_id: "WB:CPI:USA", observations: [{ obs_date: "2024-01-31", value: 6.4 }, { obs_date: "2025-01-31", value: 3.1 }] },
  "WB:CPI:DEU": { series_id: "WB:CPI:DEU", observations: [{ obs_date: "2024-01-31", value: 8.7 }, { obs_date: "2025-01-31", value: 5.9 }] },
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const id = url.split("/").pop()!;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(DETAIL[id]) });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("MacroCompare", () => {
  it("defaults to a comparison TABLE sorted by latest desc with the 1y change", async () => {
    render(<MacroCompare category="inflation" series={SERIES} />);
    expect(await screen.findByText("Latest")).toBeInTheDocument(); // table header
    expect(screen.getByText(/Δ 1y/)).toBeInTheDocument();
    // Germany (5.9) ranks above the United States (3.1)
    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const de = rows.findIndex((t) => t.includes("Germany"));
    const us = rows.findIndex((t) => t.includes("United States"));
    expect(de).toBeGreaterThan(0);
    expect(de).toBeLessThan(us);
    // latest values formatted with the % unit
    expect(screen.getByText("5.90%")).toBeInTheDocument();
    expect(screen.getByText("3.10%")).toBeInTheDocument();
    // 1y change US = 3.1 − 6.4 = −3.30 (unit-less in the Δ column)
    expect(screen.getByText("-3.30")).toBeInTheDocument();
  });

  it("toggles to the line chart on demand", async () => {
    render(<MacroCompare category="inflation" series={SERIES} />);
    await screen.findByText("Latest");
    fireEvent.click(screen.getByRole("button", { name: /^chart$/i }));
    expect(document.querySelector("svg")).toBeTruthy(); // chart now drawn
    expect(screen.queryByText("Latest")).toBeNull(); // table header gone
  });
});
