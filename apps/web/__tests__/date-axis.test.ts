import { describe, expect, it } from "vitest";

import { dateAxisTicks, tickAnchor } from "@/lib/date-axis";

const t = (iso: string) => new Date(iso).getTime();

describe("dateAxisTicks (anchored endpoints + nice interior)", () => {
  it("always anchors the exact first/last dates at the ends", () => {
    const ticks = dateAxisTicks(t("2001-06-15"), t("2026-06-19"), 6);
    expect(ticks[0].t).toBe(t("2001-06-15")); // starts at the beginning (the user's ask)
    expect(ticks[ticks.length - 1].t).toBe(t("2026-06-19"));
  });

  it("multi-year: interior ticks sit on Jan-1 year boundaries; labels are 4-digit years", () => {
    const ticks = dateAxisTicks(t("2001-06-15"), t("2026-06-19"), 6);
    expect(ticks.length).toBeGreaterThan(3);
    expect(ticks.every((x) => /^\d{4}$/.test(x.label))).toBe(true);
    const interior = ticks.slice(1, -1);
    expect(interior.every((x) => new Date(x.t).getUTCMonth() === 0 && new Date(x.t).getUTCDate() === 1)).toBe(true);
  });

  it("months: interior ticks on month-1st boundaries; labels 'Mon YY'", () => {
    const ticks = dateAxisTicks(t("2024-01-10"), t("2024-12-20"), 6);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{2}$/.test(x.label))).toBe(true);
    expect(ticks.slice(1, -1).every((x) => new Date(x.t).getUTCDate() === 1)).toBe(true);
  });

  it("short span: day labels 'Mon D'", () => {
    const ticks = dateAxisTicks(t("2024-06-01"), t("2024-06-20"), 6);
    expect(ticks.every((x) => /^[A-Z][a-z]{2} \d{1,2}$/.test(x.label))).toBe(true);
  });

  it("prunes interior ticks that collide with an endpoint (no duplicate of the end year)", () => {
    // the 2026-01-01 boundary is within 7% of the 2026-06-19 end -> dropped, so "2026" appears
    // only ONCE (the end endpoint itself), not twice.
    const ticks = dateAxisTicks(t("2001-06-15"), t("2026-06-19"), 6);
    const labels = ticks.map((x) => x.label);
    expect(labels.filter((l) => l === "2026")).toHaveLength(1);
    expect(labels[labels.length - 1]).toBe("2026");
  });

  it("returns [] for a non-positive span", () => {
    expect(dateAxisTicks(t("2024-06-01"), t("2024-06-01"))).toEqual([]);
  });

  it("tickAnchor edges: first=start, last=end, interior=middle", () => {
    expect(tickAnchor(0, 5)).toBe("start");
    expect(tickAnchor(4, 5)).toBe("end");
    expect(tickAnchor(2, 5)).toBe("middle");
  });
});
