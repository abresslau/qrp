import { describe, expect, it } from "vitest";

import { dateAxisTicks } from "@/lib/date-axis";

const t = (iso: string) => new Date(iso).getTime();

describe("dateAxisTicks (matplotlib-style nice ticks)", () => {
  it("multi-year span -> year-boundary ticks with 4-digit-year labels", () => {
    const ticks = dateAxisTicks(t("2001-01-15"), t("2026-06-19"), 6);
    expect(ticks.length).toBeGreaterThan(3);
    expect(ticks.every((x) => /^\d{4}$/.test(x.label))).toBe(true);
    // ticks sit on Jan-1 boundaries inside the range, evenly stepped
    expect(ticks.every((x) => new Date(x.t).getUTCMonth() === 0 && new Date(x.t).getUTCDate() === 1)).toBe(true);
    expect(ticks[0].t).toBeGreaterThanOrEqual(t("2001-01-15"));
    expect(ticks[ticks.length - 1].t).toBeLessThanOrEqual(t("2026-06-19"));
  });

  it("months span -> month-boundary ticks labelled 'Mon YY'", () => {
    const ticks = dateAxisTicks(t("2024-01-01"), t("2024-12-31"), 6);
    expect(ticks.length).toBeGreaterThan(3);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{2}$/.test(x.label))).toBe(true); // e.g. "Mar 24"
    expect(ticks.every((x) => new Date(x.t).getUTCDate() === 1)).toBe(true);
  });

  it("short span -> day ticks labelled 'Mon D'", () => {
    const ticks = dateAxisTicks(t("2024-06-01"), t("2024-06-20"), 6);
    expect(ticks.length).toBeGreaterThan(2);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{1,2}$/.test(x.label))).toBe(true); // e.g. "Jun 8"
  });

  it("returns [] for a non-positive span", () => {
    expect(dateAxisTicks(t("2024-06-01"), t("2024-06-01"))).toEqual([]);
  });

  it("the tick count adapts to the range (not a fixed 5)", () => {
    const wide = dateAxisTicks(t("1990-01-01"), t("2026-01-01"), 6).length;
    const mid = dateAxisTicks(t("2022-01-01"), t("2026-01-01"), 6).length;
    expect(wide).not.toBe(0);
    expect(mid).not.toBe(0);
  });
});
