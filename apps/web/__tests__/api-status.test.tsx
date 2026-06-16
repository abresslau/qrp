import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiStatus } from "@/components/api-status";
import { setOnline } from "@/lib/connection";

beforeEach(() => setOnline(true)); // reset the shared module store between tests
afterEach(() => vi.unstubAllGlobals());

describe("ApiStatus (sidebar API indicator + offline toggle)", () => {
  it("online + reachable → connected (emerald), 'API connected' tooltip", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })));
    render(<ApiStatus />);
    const btn = await screen.findByRole("button");
    await vi.waitFor(() => expect(btn).toHaveAttribute("data-status", "up"));
    expect(btn.className).toContain("emerald");
    expect(btn.getAttribute("title")).toMatch(/API connected/);
  });

  it("online + unreachable → down (rose), 'API unreachable' tooltip", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("down"))));
    render(<ApiStatus />);
    const btn = await screen.findByRole("button");
    await vi.waitFor(() => expect(btn).toHaveAttribute("data-status", "down"));
    expect(btn.className).toContain("rose");
    expect(btn.getAttribute("title")).toMatch(/API unreachable/);
  });

  it("polls every 15s while online, PAUSES while offline, RESUMES on reconnect", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
      vi.stubGlobal("fetch", fetchMock);

      await act(async () => {
        render(<ApiStatus />);
      });
      const btn = screen.getByRole("button");
      expect(fetchMock).toHaveBeenCalledTimes(1); // ping on mount

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15000);
      });
      expect(fetchMock).toHaveBeenCalledTimes(2); // a poll fired while online

      // go offline → grey/paused, polling stops
      await act(async () => {
        fireEvent.click(btn);
      });
      expect(btn).toHaveAttribute("data-status", "off");
      expect(btn.className).toContain("muted");
      const offCount = fetchMock.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(45000);
      });
      expect(fetchMock.mock.calls.length).toBe(offCount); // NO polls while offline

      // reconnect → immediate ping resumes, status returns
      await act(async () => {
        fireEvent.click(btn);
      });
      expect(fetchMock.mock.calls.length).toBe(offCount + 1);
      expect(btn).toHaveAttribute("data-status", "up");
    } finally {
      vi.useRealTimers();
    }
  });
});
