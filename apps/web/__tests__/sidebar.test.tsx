import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/sidebar";

// usePathname is read live from a mutable holder so a test can simulate a route change and
// re-render. next/link -> a plain anchor (no router context in jsdom); ThemeToggle stubbed
// (it touches matchMedia/localStorage, irrelevant to the registry fail-safe).
const nav = vi.hoisted(() => ({ pathname: "/sym" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/theme-toggle", () => ({ ThemeToggle: () => null }));

const MODULES = [
  { key: "sym", name: "Sym", description: "", enabled: true }, // static submenu
  { key: "macro", name: "Macro", description: "", enabled: true }, // async (fetch) submenu
];

function stubCategories(behaviour: "reject" | "ok") {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/macro/categories")) {
        return behaviour === "ok"
          ? Promise.resolve({ ok: true, json: () => Promise.resolve([{ category: "Rates", n_series: 3 }]) })
          : Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }),
  );
}

function categoriesCalls() {
  return (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls
    .map((c) => c[0] as string)
    .filter((u) => u.includes("/macro/categories"));
}

beforeEach(() => {
  nav.pathname = "/sym";
  try {
    localStorage.removeItem("qrp-sidebar-collapsed");
  } catch {
    /* ignore */
  }
});
afterEach(() => vi.unstubAllGlobals());

describe("Sidebar collapse/expand", () => {
  it("collapses to a rail (labels → initials, theme hidden) and expands back, persisting", async () => {
    stubCategories("ok");
    const { rerender } = render(<Sidebar name="QRP" tagline="Quant" modules={MODULES} />);

    // expanded: full module label + collapse control
    expect(screen.getByText("Sym")).toBeInTheDocument();
    const collapseBtn = screen.getByLabelText("Collapse sidebar");
    fireEvent.click(collapseBtn);

    // collapsed: the expand control appears, the full label is gone, the initial shows
    expect(screen.getByLabelText("Expand sidebar")).toBeInTheDocument();
    expect(screen.queryByText("Sym")).not.toBeInTheDocument();
    // module link still navigable (aria-label keeps the full name)
    expect(screen.getByLabelText("Sym")).toHaveAttribute("href", "/sym");
    // persisted
    expect(localStorage.getItem("qrp-sidebar-collapsed")).toBe("1");

    // expand again
    fireEvent.click(screen.getByLabelText("Expand sidebar"));
    expect(screen.getByText("Sym")).toBeInTheDocument();
    expect(localStorage.getItem("qrp-sidebar-collapsed")).toBe("0");
    rerender(<Sidebar name="QRP" tagline="Quant" modules={MODULES} />);
  });

  it("starts collapsed when localStorage says so", () => {
    localStorage.setItem("qrp-sidebar-collapsed", "1");
    stubCategories("ok");
    render(<Sidebar name="QRP" modules={MODULES} />);
    expect(screen.getByLabelText("Expand sidebar")).toBeInTheDocument();
    expect(screen.queryByText("Macro")).not.toBeInTheDocument(); // label hidden in the rail
  });
});

describe("Sidebar async-submenu fail-safe (QH.7 / AC3)", () => {
  it("does not crash when a fetch provider throws — the module label still renders", async () => {
    stubCategories("reject");
    render(<Sidebar name="QRP" modules={MODULES} />);
    // both module labels present; the failed macro submenu simply has no items.
    expect(screen.getByText("Sym")).toBeInTheDocument();
    expect(screen.getByText("Macro")).toBeInTheDocument();
    // let the rejected load settle; nothing throws.
    await Promise.resolve();
  });

  it("retries a FAILED load on a later route change (un-latched)", async () => {
    stubCategories("reject");
    const { rerender } = render(<Sidebar name="QRP" modules={MODULES} />);
    await vi.waitFor(() => expect(categoriesCalls().length).toBe(1));

    nav.pathname = "/macro"; // route change
    rerender(<Sidebar name="QRP" modules={MODULES} />);
    await vi.waitFor(() => expect(categoriesCalls().length).toBe(2)); // failed load is retried
  });

  it("does NOT re-fetch after a successful load across route changes (latched)", async () => {
    stubCategories("ok");
    const { rerender } = render(<Sidebar name="QRP" modules={MODULES} />);
    // Wait for the load to fully COMMIT (submenu present => loadedOkRef latched) before the
    // route change — asserting the call count alone would race the latch's microtask.
    expect(await screen.findByLabelText("Expand Macro")).toBeInTheDocument();
    expect(categoriesCalls().length).toBe(1);

    nav.pathname = "/macro";
    rerender(<Sidebar name="QRP" modules={MODULES} />);
    // active macro -> expanded -> the fetched category shows
    expect(await screen.findByText("Rates")).toBeInTheDocument();
    // still exactly one fetch: a successful (even empty) load is not retried
    await Promise.resolve();
    expect(categoriesCalls().length).toBe(1);
  });
});
