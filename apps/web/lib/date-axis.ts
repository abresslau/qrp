// Shared date-axis ticks for the platform's SVG time-series charts.
//
// Canonical reference: matplotlib's AutoDateLocator / D3 scaleTime.ticks() place EVENLY-spaced
// ticks at a "nice" round step (years [1,2,4,5,10], months [1,2,3,4,6], days [1,2,3,7,14]) and let
// the endpoints float — they rely on the axis having margins. Our charts draw the series
// edge-to-edge (no margin), so a floating first tick leaves the left edge blank.
//
// Fix: keep the canonical EVEN round step, but PHASE it from the data start — the first tick is the
// start (anchored left edge), every gap is exactly one step (even spacing), the right edge floats by
// < 1 step. Crucially the UNIT (day/month/year) is chosen by span so the step yields enough ticks
// (matplotlib's "minticks" idea) AND labels are formatted in that unit — so a 2-year span uses month
// steps + month labels, never a 1-year step that yields just two ticks.
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

const yearLabel = (t: number) => String(new Date(t).getUTCFullYear());
const monthLabel = (t: number) =>
  new Date(t).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
const dayLabel = (t: number) =>
  new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/**
 * Evenly-spaced date ticks across [minT, maxT] (ms epoch), phased from the START. The unit is chosen
 * by span — days (≤ ~70d), months (≤ ~3y), else years — so the round step yields a sensible count;
 * labels are formatted in that unit. First tick is exactly `minT` (anchored left edge); last is ≤
 * `maxT` (right edge floats < 1 step). Returns [] for a non-positive span.
 */
export function dateAxisTicks(minT: number, maxT: number, target = 6): AxisTick[] {
  if (!(maxT > minT)) return [];
  const spanDays = (maxT - minT) / DAY;

  let at: (k: number) => number;
  let label: (t: number) => string;
  if (spanDays <= 70) {
    const step = niceStep(spanDays / target, [1, 2, 3, 7, 14]);
    at = (k) => minT + k * step * DAY;
    label = dayLabel;
  } else if (spanDays <= 365 * 3) {
    const step = niceStep(spanDays / 30.44 / target, [1, 2, 3, 4, 6]);
    at = (k) => addMonths(minT, k * step);
    label = monthLabel;
  } else {
    const step = niceStep(spanDays / 365.25 / target, [1, 2, 4, 5, 10, 20, 25, 50, 100]);
    at = (k) => addYears(minT, k * step);
    label = yearLabel;
  }

  const out: AxisTick[] = [];
  for (let k = 0; ; k++) {
    const t = at(k);
    if (t > maxT) break;
    out.push({ t, label: label(t) });
    if (out.length > 64) break; // safety against a degenerate zero/tiny step
  }
  if (out.length < 2) return [minT, maxT].map((t) => ({ t, label: label(t) }));
  return out;
}

/**
 * SVG textAnchor by tick index. The first tick sits on the left edge (left-align so it doesn't clip);
 * all others (including the last, which floats inside) are centered.
 */
export function tickAnchor(i: number): "start" | "middle" {
  return i === 0 ? "start" : "middle";
}
