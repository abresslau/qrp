import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/lib/api";
import { CommandPalette } from "@/components/command-palette";

type OpDef = Schemas["OpDef"];

// next/navigation router is mocked; we assert on push().
const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push }) }));

// Mock the registry with a SMALL controlled fixture so the filter/selection tests don't couple
// to the live SUBNAV_PROVIDERS contents/ordering (AC2: "mocked registry"). Screen order here is
// the fixture order: Overview, Explorer, Universes.
vi.mock("@/lib/nav", () => ({
  SUBNAV_PROVIDERS: {
    sym: {
      kind: "static",
      items: [
        { href: "/sym", label: "Overview" },
        { href: "/sym/explorer", label: "Explorer" },
        { href: "/sym/universes", label: "Universes" },
      ],
    },
  },
}));

const MODULES = [
  { key: "sym", name: "Sym", description: "", enabled: true }, // has the (mocked) static submenu
  { key: "signal", name: "Signal", description: "", enabled: true }, // no submenu provider
];

function op(over: Partial<OpDef> = {}): OpDef {
  return { key: "map", label: "Map", writes: false, takes_universe: false, takes_scope: false, ...over } as OpDef;
}

// Route fetch: ops list on open, and the POST /run with a configurable result.
function stubFetch(opts: { ops?: OpDef[]; run?: { httpOk?: boolean; body?: unknown } } = {}) {
  const { ops = [], run = { httpOk: true, body: { ok: true, job_id: 1 } } } = opts;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.includes("/operate/ops")) return Promise.resolve({ ok: true, json: () => Promise.resolve(ops) });
      if (url.includes("/operate/run")) return Promise.resolve({ ok: run.httpOk ?? true, json: () => Promise.resolve(run.body) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }),
  );
}

function openPalette() {
  fireEvent.keyDown(window, { key: "k", metaKey: true });
}

// The currently-selected row carries the active style token.
function activeLabel(): string | null {
  const btn = document.querySelector("button.bg-fg\\/10");
  return btn?.textContent ?? null;
}

beforeEach(() => {
  nav.push.mockClear();
  stubFetch();
});
afterEach(() => vi.unstubAllGlobals());

describe("CommandPalette (QH.7 / AC2)", () => {
  it("is closed until ⌘K, then opens", () => {
    render(<CommandPalette modules={MODULES} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    openPalette();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("substring-filters entries (areas + screens) by the query", async () => {
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    await userEvent.type(screen.getByPlaceholderText(/Jump to a module/), "explorer");
    expect(screen.getByText("Sym: Explorer")).toBeInTheDocument();
    expect(screen.queryByText("Sym: Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Sym")).not.toBeInTheDocument(); // the area doesn't match "explorer"
  });

  it("Enter navigates to the selected screen and closes", () => {
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    const input = screen.getByPlaceholderText(/Jump to a module/);
    fireEvent.change(input, { target: { value: "explorer" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(nav.push).toHaveBeenCalledWith("/sym/explorer");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("↓ moves the selection (clamped, no wrap) before Enter acts", () => {
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    const input = screen.getByPlaceholderText(/Jump to a module/);
    fireEvent.change(input, { target: { value: "sym:" } }); // 3 "Sym: …" screens in fixture order
    expect(activeLabel()).toBe("Sym: Overview"); // selection starts at 0
    fireEvent.keyDown(input, { key: "ArrowDown" }); // -> Explorer (2nd)
    expect(activeLabel()).toBe("Sym: Explorer");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(nav.push).toHaveBeenCalledWith("/sym/explorer");
  });

  it("↑ clamps at the top (no wrap) — Enter acts on the first row", () => {
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    const input = screen.getByPlaceholderText(/Jump to a module/);
    fireEvent.change(input, { target: { value: "sym:" } });
    fireEvent.keyDown(input, { key: "ArrowUp" }); // already at 0 -> stays at 0 (no wrap to last)
    expect(activeLabel()).toBe("Sym: Overview");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(nav.push).toHaveBeenCalledWith("/sym");
  });

  it("launches a read-only op directly then routes to Operate on success", async () => {
    stubFetch({ ops: [op({ key: "map", label: "Map", writes: false })], run: { httpOk: true, body: { ok: true, job_id: 7 } } });
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    await userEvent.click(await screen.findByText("Run: Map"));
    await waitFor(() => {
      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
      expect(calls.some((u) => u.includes("/operate/run"))).toBe(true);
      expect(nav.push).toHaveBeenCalledWith("/sym/operate");
    });
  });

  it("surfaces a rejection inline and keeps the palette open (the QH.6 AC5 fix)", async () => {
    stubFetch({ ops: [op({ key: "map", label: "Map", writes: false })], run: { httpOk: true, body: { ok: false, error: { message: "duplicate run" } } } });
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    await userEvent.click(await screen.findByText("Run: Map"));
    expect(await screen.findByText(/Rejected: duplicate run/)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // stays open
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("routes a writer op to Operate WITHOUT POSTing /run", async () => {
    stubFetch({ ops: [op({ key: "load", label: "Load", writes: true })] });
    render(<CommandPalette modules={MODULES} />);
    openPalette();
    await userEvent.click(await screen.findByText("Run: Load"));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/sym/operate"));
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes("/operate/run"))).toBe(false);
  });
});
