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
    universe_id: "sp500", name: "S&P 500", members_resolved: 101, active_members: 100,
    prices: { covered: 100, total: 100, latest_date: "2026-06-18", status: "ok" },
    returns: { covered: 100, total: 100, latest_date: "2026-06-18", status: "ok" },
    fundamentals: { covered: 98, total: 100, latest_date: "2026-06-16", status: "partial" },
  },
  {
    universe_id: "ibov", name: "Ibovespa", members_resolved: 78, active_members: 78,
    prices: { covered: 60, total: 78, latest_date: "2026-06-17", status: "partial" },
    returns: { covered: 0, total: 78, latest_date: null, status: "missing" },
    fundamentals: { covered: 78, total: 78, latest_date: "2026-06-12", status: "ok" },
  },
];

// The page fetches coverage + the universe list (for the map's selector). Return the coverage
// ROWS for the coverage call and an empty universe list (keeps the map's <select> from
// duplicating universe names that the table assertions query for).
function mockApi() {
  apiGet.mockImplementation((path: string) =>
    path.endsWith("/coverage") ? Promise.resolve(ROWS) : Promise.resolve([]),
  );
  // The map is a client component that fetches by-country via global fetch; stub it to empty so
  // it mounts cleanly inside this server-page test.
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })));
}

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("Universes coverage landing", () => {
  it("renders the layer columns incl. Active + per-layer coverage & status", async () => {
    mockApi();
    render(await UniversesPage());

    for (const h of ["Universe", "Members", "Active", "Prices", "Returns", "Fundamentals"]) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "S&P 500" })).toBeInTheDocument();
    expect(screen.getByText("60/78")).toBeInTheDocument(); // ibov prices, partial
    expect(screen.getByText("0/78")).toBeInTheDocument(); // ibov returns, missing
    // sp500 has 1 delisted member (101 resolved, 100 active) → the −1 indicator is shown
    expect(screen.getByText("−1")).toBeInTheDocument();
    expect(screen.getAllByText("missing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("partial").length).toBeGreaterThan(0);
  });

  it("degrades to a message when the coverage API is unreachable", async () => {
    apiGet.mockRejectedValue(new Error("down"));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })));
    render(await UniversesPage());
    expect(screen.getByText(/No universe coverage/)).toBeInTheDocument();
  });
});
