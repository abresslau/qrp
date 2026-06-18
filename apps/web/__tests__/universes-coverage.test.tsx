import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
const apiGet = vi.fn();
vi.mock("@/lib/api", () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));

import UniversesPage from "@/app/sym/page";

const ROWS = [
  {
    universe_id: "sp500", name: "S&P 500", members_resolved: 100,
    prices: { covered: 100, total: 100, latest_date: "2026-06-18", status: "ok" },
    returns: { covered: 100, total: 100, latest_date: "2026-06-18", status: "ok" },
    fundamentals: { covered: 98, total: 100, latest_date: "2026-06-16", status: "partial" },
  },
  {
    universe_id: "ibov", name: "Ibovespa", members_resolved: 78,
    prices: { covered: 60, total: 78, latest_date: "2026-06-17", status: "partial" },
    returns: { covered: 0, total: 78, latest_date: null, status: "missing" },
    fundamentals: { covered: 78, total: 78, latest_date: "2026-06-12", status: "ok" },
  },
];

afterEach(() => vi.clearAllMocks());

describe("Universes coverage landing", () => {
  it("renders the three layer columns + per-layer coverage & status", async () => {
    apiGet.mockResolvedValue(ROWS);
    render(await UniversesPage());

    for (const h of ["Universe", "Members", "Prices", "Returns", "Fundamentals"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    expect(screen.getByText("S&P 500")).toBeInTheDocument();
    expect(screen.getByText("60/78")).toBeInTheDocument(); // ibov prices, partial
    expect(screen.getByText("0/78")).toBeInTheDocument(); // ibov returns, missing
    // the gaps are flagged
    expect(screen.getAllByText("missing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("partial").length).toBeGreaterThan(0);
  });

  it("degrades to a message when the coverage API is unreachable", async () => {
    apiGet.mockRejectedValue(new Error("down"));
    render(await UniversesPage());
    expect(screen.getByText(/No universe coverage/)).toBeInTheDocument();
  });
});
