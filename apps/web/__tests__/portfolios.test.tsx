import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PortfoliosPage from "@/app/portfolios/page";

// next/link -> a plain anchor (no router context in jsdom).
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

// fetch behaviour is toggled per phase: "fail" rejects the mount load, "ok" returns rows.
const state = vi.hoisted(() => ({ mode: "fail" as "fail" | "ok" }));
function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (state.mode === "fail") return Promise.reject(new Error("down"));
      if (url.includes("/portfolios/clients")) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes("/api/portfolios"))
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([{ portfolio_id: 1, name: "Growth", client: "", n_weights: 3, latest_as_of_date: "2026-06-01" }]),
        });
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }),
  );
}

beforeEach(() => {
  state.mode = "fail";
  stub();
});
afterEach(() => vi.unstubAllGlobals());

describe("PortfoliosPage load-failure surfacing (QH.8 / AC5)", () => {
  it("shows an error + retry on a failed mount load, then renders rows after a successful retry", async () => {
    render(<PortfoliosPage />);

    // failure is surfaced (not a silent empty list)
    expect(await screen.findByText(/Couldn.t load portfolios/)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry" });

    // retry succeeds -> rows render, error gone
    state.mode = "ok";
    await userEvent.click(retry);
    expect(await screen.findByText("Growth")).toBeInTheDocument();
    expect(screen.queryByText(/Couldn.t load portfolios/)).not.toBeInTheDocument();
  });

  it("surfaces an HTTP error (500) as a failure, not as a parsed list (AC5 / r.ok)", async () => {
    state.mode = "ok"; // bypass the reject path; force a 500-with-body instead
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) })),
    );
    render(<PortfoliosPage />);
    expect(await screen.findByText(/Couldn.t load portfolios/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("distinguishes a real empty result from a failure", async () => {
    state.mode = "ok";
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })),
    );
    render(<PortfoliosPage />);
    expect(await screen.findByText(/No portfolios yet/)).toBeInTheDocument();
    expect(screen.queryByText(/Couldn.t load portfolios/)).not.toBeInTheDocument();
  });
});
