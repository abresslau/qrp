import { describe, expect, it } from "vitest";

import { dateAxisTicks, tickAnchor } from "@/lib/date-axis";

const t = (iso: string) => new Date(iso).getTime();

describe("dateAxisTicks (even round step, phased from the start)", () => {
  it("anchors the first tick exactly at the data start; last tick floats <= end", () => {
    const ticks = dateAxisTicks(t("2001-06-15"), t("2026-06-19"), 6);
    expect(ticks[0].t).toBe(t("2001-06-15")); // beginning is anchored (the user's ask)
    expect(ticks[ticks.length - 1].t).toBeLessThanOrEqual(t("2026-06-19"));
  });

  it("multi-year: a constant round year step (even spacing), 4-digit-year labels", () => {
    const ticks = dateAxisTicks(t("2001-06-15"), t("2026-06-19"), 6);
    expect(ticks.every((x) => /^\d{4}$/.test(x.label))).toBe(true);
    const yrs = ticks.map((x) => Number(x.label));
    const diffs = yrs.slice(1).map((y, i) => y - yrs[i]);
    expect(new Set(diffs).size).toBe(1); // one constant step => evenly spaced
    expect(diffs[0]).toBe(5); // 25y / 6 -> nice step 5
  });

  it("months: a constant month step, 'Mon YY' labels", () => {
    const ticks = dateAxisTicks(t("2024-01-10"), t("2024-12-20"), 6);
    expect(ticks.length).toBeGreaterThan(3);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{2}$/.test(x.label))).toBe(true);
    // consecutive ticks are a constant number of months apart (calendar-even)
    const stepMonths = ticks.slice(1).map((x, i) => {
      const a = new Date(ticks[i].t);
      const b = new Date(x.t);
      return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + (b.getUTCMonth() - a.getUTCMonth());
    });
    expect(new Set(stepMonths).size).toBe(1);
  });

  it("2-year span uses month steps (not a 1-year step that yields just 2 ticks)", () => {
    // regression: 730d crossed the year threshold and gave only 2 yearly ticks labelled as months.
    const ticks = dateAxisTicks(t("2024-06-20"), t("2026-06-19"), 6);
    expect(ticks.length).toBeGreaterThanOrEqual(5);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{2}$/.test(x.label))).toBe(true); // month labels
  });

  it("short span: day labels 'Mon D'", () => {
    const ticks = dateAxisTicks(t("2024-06-01"), t("2024-06-20"), 6);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{1,2}$/.test(x.label))).toBe(true);
    expect(ticks[0].t).toBe(t("2024-06-01"));
  });

  it("count adapts to the range (more ticks for a wider span at the same target)", () => {
    const wide = dateAxisTicks(t("1990-01-01"), t("2026-01-01"), 6).length;
    const narrow = dateAxisTicks(t("2024-01-01"), t("2026-01-01"), 6).length;
    expect(wide).toBeGreaterThan(2);
    expect(narrow).toBeGreaterThan(2);
  });

  it("returns [] for a non-positive span", () => {
    expect(dateAxisTicks(t("2024-06-01"), t("2024-06-01"))).toEqual([]);
  });

  it("tickAnchor: first=start (left edge), rest=middle", () => {
    expect(tickAnchor(0)).toBe("start");
    expect(tickAnchor(1)).toBe("middle");
    expect(tickAnchor(5)).toBe("middle");
  });
});
