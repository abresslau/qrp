import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useRunGuard } from "@/lib/use-run-guard";

describe("useRunGuard", () => {
  it("begin(): a newer run supersedes an older one", () => {
    const { result } = renderHook(() => useRunGuard());
    const first = result.current.begin();
    expect(first()).toBe(true);
    const second = result.current.begin(); // newer run
    expect(first()).toBe(false); // the older run is now stale
    expect(second()).toBe(true);
  });

  it("supersede() + capture(): a capture is invalidated by a later supersede (the reopen case)", () => {
    const { result } = renderHook(() => useRunGuard());
    result.current.supersede(); // session A
    const inSessionA = result.current.capture();
    expect(inSessionA()).toBe(true);
    result.current.supersede(); // session B (e.g. modal reopened)
    expect(inSessionA()).toBe(false); // the session-A capture is stale
    const inSessionB = result.current.capture();
    expect(inSessionB()).toBe(true);
  });

  it("isCurrent() is false after the component unmounts", () => {
    const { result, unmount } = renderHook(() => useRunGuard());
    const run = result.current.begin();
    expect(run()).toBe(true);
    act(() => unmount());
    expect(run()).toBe(false); // a resolution after unmount is guarded
  });

  it("the returned object is stable across renders (safe in effect deps)", () => {
    const { result, rerender } = renderHook(() => useRunGuard());
    const g1 = result.current;
    rerender();
    expect(result.current).toBe(g1); // same identity → no effect churn
  });
});
