// Shared date-axis ticks for the platform's SVG time-series charts.
//
// Design (see study): the series is drawn edge-to-edge with no x-margin, so we ALWAYS anchor the
// two endpoints (the real first/last dates sit at the axis edges) and fill the INTERIOR with
// matplotlib-style "nice" round boundaries — year boundaries for multi-year ranges, month
// boundaries for months, day boundaries for short ranges. Interior ticks too close to an endpoint
// are dropped so labels never collide with the anchored ends. Labels are formatted by granularity.
//
// Dates here are date-only ISO strings (UTC midnight), so everything is computed/formatted in UTC.

export type AxisTick = { t: number; label: string };

const DAY = 86_400_000;
// Drop an interior tick within this fraction of the span from either endpoint (anti-collision).
const EDGE_GAP = 0.07;

function niceStep(rough: number, ladder: number[]): number {
  for (const s of ladder) if (rough <= s) return s;
  return ladder[ladder.length - 1];
}

function yearLabel(t: number): string {
  return String(new Date(t).getUTCFullYear());
}
function monthLabel(t: number): string {
  return new Date(t).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
}
function dayLabel(t: number): string {
  return new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** Granularity-appropriate label for a time, given the total span in days. */
export function fmtAxisDate(t: number, spanDays: number): string {
  if (spanDays > 365 * 2.5) return yearLabel(t);
  return spanDays > 70 ? monthLabel(t) : dayLabel(t);
}

/** Round-boundary candidate ticks strictly INSIDE (minT, maxT) for the span's natural unit. */
function interiorBoundaries(minT: number, maxT: number, spanDays: number, target: number): number[] {
  const out: number[] = [];
  if (spanDays > 365 * 1.5) {
    const step = niceStep(spanDays / 365.25 / target, [1, 2, 5, 10, 25, 50, 100]);
    const y0 = Math.ceil(new Date(minT).getUTCFullYear() / step) * step;
    for (let y = y0; ; y += step) {
      const t = Date.UTC(y, 0, 1);
      if (t >= maxT) break;
      if (t > minT) out.push(t);
    }
  } else if (spanDays > 70) {
    const step = niceStep(spanDays / 30.44 / target, [1, 2, 3, 6]);
    const d0 = new Date(minT);
    let y = d0.getUTCFullYear();
    let m = Math.ceil(d0.getUTCMonth() / step) * step;
    y += Math.floor(m / 12);
    m %= 12;
    for (;;) {
      const t = Date.UTC(y, m, 1);
      if (t >= maxT) break;
      if (t > minT) out.push(t);
      m += step;
      while (m >= 12) {
        m -= 12;
        y += 1;
      }
    }
  } else {
    const step = niceStep(spanDays / target, [1, 2, 5, 7, 14, 28]);
    const start = Math.ceil(minT / DAY) * DAY;
    for (let t = start; t < maxT; t += step * DAY) if (t > minT) out.push(t);
  }
  return out;
}

/**
 * Anchored date ticks across [minT, maxT] (ms epoch): the two endpoints plus span-appropriate
 * round interior boundaries (~`target` total), interior ticks near an endpoint pruned. Returns
 * [] for a non-positive span, or a single tick when min===max degenerately handled by callers.
 */
export function dateAxisTicks(minT: number, maxT: number, target = 6): AxisTick[] {
  if (!(maxT > minT)) return [];
  const spanDays = (maxT - minT) / DAY;
  const gap = (maxT - minT) * EDGE_GAP;
  const startLabel = fmtAxisDate(minT, spanDays);
  const endLabel = fmtAxisDate(maxT, spanDays);
  const interior = interiorBoundaries(minT, maxT, spanDays, target)
    .filter((t) => t - minT > gap && maxT - t > gap)
    .map((t) => ({ t, label: fmtAxisDate(t, spanDays) }))
    // drop an interior tick whose (coarse) label duplicates an endpoint's — e.g. a "Jun 26"
    // month boundary sitting next to a "Jun 26" end date.
    .filter((tk) => tk.label !== startLabel && tk.label !== endLabel);
  return [{ t: minT, label: startLabel }, ...interior, { t: maxT, label: endLabel }];
}

/** SVG textAnchor by tick index so the anchored first/last labels don't clip the chart edges. */
export function tickAnchor(i: number, count: number): "start" | "middle" | "end" {
  if (i === 0) return "start";
  if (i === count - 1) return "end";
  return "middle";
}
