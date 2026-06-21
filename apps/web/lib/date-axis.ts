// Shared date-axis ticks for the platform's SVG time-series charts.
//
// Canonical reference: matplotlib's AutoDateLocator / D3 scaleTime.ticks() place EVENLY-spaced
// ticks at a "nice" round step (years [1,2,4,5,10], months [1,2,3,4,6], days [1,2,3,7,14]) and let
// the endpoints float — they rely on the axis having margins. Our charts draw the series
// edge-to-edge (no margin), so a floating first tick leaves the left edge blank.
//
// Fix: keep the canonical EVEN round step, but PHASE it from the data start — the first tick is the
// start (anchored left edge), every gap is exactly one step (even spacing), and only the right edge
// floats by < 1 step. Even + anchored-start + dynamic count.
//
// Dates here are date-only ISO strings (UTC midnight); compute/format in UTC to avoid a tz shift.

export type AxisTick = { t: number; label: string };

const DAY = 86_400_000;

function niceStep(rough: number, ladder: number[]): number {
  for (const s of ladder) if (rough <= s) return s;
  return ladder[ladder.length - 1];
}

function addYears(t: number, n: number): number {
  const d = new Date(t);
  return Date.UTC(d.getUTCFullYear() + n, d.getUTCMonth(), d.getUTCDate());
}
function addMonths(t: number, n: number): number {
  const d = new Date(t);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, d.getUTCDate());
}

/** Granularity-appropriate label for a time, given the total span in days. */
export function fmtAxisDate(t: number, spanDays: number): string {
  const d = new Date(t);
  if (spanDays > 365 * 2.5) return String(d.getUTCFullYear());
  if (spanDays > 70) return d.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/**
 * Evenly-spaced date ticks across [minT, maxT] (ms epoch), phased from the START: tick k = start +
 * k·step where step is a nice round interval (year/month/day) chosen for ~`target` ticks. The first
 * tick is exactly `minT` (anchored left edge); the last is ≤ `maxT` (right edge floats < 1 step).
 * Returns [] for a non-positive span.
 */
export function dateAxisTicks(minT: number, maxT: number, target = 6): AxisTick[] {
  if (!(maxT > minT)) return [];
  const spanDays = (maxT - minT) / DAY;
  const at = (k: number): number => {
    if (spanDays > 365 * 1.5) {
      const step = niceStep(spanDays / 365.25 / target, [1, 2, 4, 5, 10, 20, 25, 50, 100]);
      return addYears(minT, k * step);
    }
    if (spanDays > 70) {
      const step = niceStep(spanDays / 30.44 / target, [1, 2, 3, 4, 6]);
      return addMonths(minT, k * step);
    }
    const step = niceStep(spanDays / target, [1, 2, 3, 7, 14]);
    return minT + k * step * DAY;
  };
  const out: AxisTick[] = [];
  for (let k = 0; ; k++) {
    const t = at(k);
    if (t > maxT) break;
    out.push({ t, label: fmtAxisDate(t, spanDays) });
    if (out.length > 64) break; // safety against a degenerate zero/tiny step
  }
  if (out.length < 2) return [minT, maxT].map((t) => ({ t, label: fmtAxisDate(t, spanDays) }));
  return out;
}

/**
 * SVG textAnchor by tick index. The first tick sits on the left edge (left-align so it doesn't clip);
 * all others (including the last, which floats inside) are centered.
 */
export function tickAnchor(i: number): "start" | "middle" {
  return i === 0 ? "start" : "middle";
}
