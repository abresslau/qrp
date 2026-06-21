// Shared date-axis ticks for the platform's SVG time-series charts.
//
// Canonical reference: matplotlib AutoDateLocator / D3 scaleTime.ticks() — evenly-spaced ticks at a
// "nice" step chosen from a date ladder (days/months/years × nice multiples), with the tick COUNT
// scaled to the available width (~1 label per 70-90px; D3 defaults to ~10). They let the endpoints
// float (relying on axis margins).
//
// Our adaptation: same width-driven count + nice ladder, but PHASE the step from the data start so
// the first tick sits on the left edge (our charts are edge-to-edge, no margin) and gaps are even;
// the right edge floats < 1 step. The step's UNIT decides the label (day "Jun 8" / month "Jun 24" /
// year "2005"), so a 5y span can use 6-month steps without duplicate year labels.
//
// Dates here are date-only ISO strings (UTC midnight); compute/format in UTC to avoid a tz shift.

export type AxisTick = { t: number; label: string };

const DAY = 86_400_000;

type Unit = "day" | "month" | "year";
// Ascending ladder of nice steps (matplotlib multiples), with an approximate length in days used
// only to pick the step nearest the ideal spacing.
const LADDER: { u: Unit; m: number; d: number }[] = [
  { u: "day", m: 1, d: 1 },
  { u: "day", m: 2, d: 2 },
  { u: "day", m: 3, d: 3 },
  { u: "day", m: 7, d: 7 },
  { u: "day", m: 14, d: 14 },
  { u: "month", m: 1, d: 30.44 },
  { u: "month", m: 2, d: 60.9 },
  { u: "month", m: 3, d: 91.3 },
  { u: "month", m: 6, d: 182.6 },
  { u: "year", m: 1, d: 365.25 },
  { u: "year", m: 2, d: 730.5 },
  { u: "year", m: 5, d: 1826.25 },
  { u: "year", m: 10, d: 3652.5 },
  { u: "year", m: 25, d: 9131.25 },
  { u: "year", m: 50, d: 18262.5 },
  { u: "year", m: 100, d: 36525 },
];

const yearLabel = (t: number) => String(new Date(t).getUTCFullYear());
const monthLabel = (t: number) =>
  new Date(t).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
const dayLabel = (t: number) =>
  new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

function addYears(t: number, n: number): number {
  const d = new Date(t);
  return Date.UTC(d.getUTCFullYear() + n, d.getUTCMonth(), d.getUTCDate());
}
function addMonths(t: number, n: number): number {
  const d = new Date(t);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, d.getUTCDate());
}

/** Desired tick count from the plot width in viewBox units (~1 label per 80px), clamped sanely. */
export function axisTickCount(plotWidth: number): number {
  return Math.max(6, Math.min(16, Math.round(plotWidth / 80)));
}

/**
 * Evenly-spaced date ticks across [minT, maxT] (ms epoch), phased from the START. `target` is the
 * desired tick count (use {@link axisTickCount} from the chart width). The step is the ladder entry
 * whose length is nearest `span/target`; labels are formatted in that step's unit. First tick is
 * exactly `minT` (anchored left edge); last is ≤ `maxT` (right floats < 1 step). [] for empty span.
 */
export function dateAxisTicks(minT: number, maxT: number, target = 10): AxisTick[] {
  if (!(maxT > minT)) return [];
  const spanDays = (maxT - minT) / DAY;
  const ideal = spanDays / Math.max(2, target);
  let pick = LADDER[0];
  for (const e of LADDER) if (Math.abs(e.d - ideal) < Math.abs(pick.d - ideal)) pick = e;

  const label = pick.u === "year" ? yearLabel : pick.u === "month" ? monthLabel : dayLabel;
  const at = (k: number): number =>
    pick.u === "year"
      ? addYears(minT, k * pick.m)
      : pick.u === "month"
        ? addMonths(minT, k * pick.m)
        : minT + k * pick.m * DAY;

  const out: AxisTick[] = [];
  for (let k = 0; ; k++) {
    const t = at(k);
    if (t > maxT) break;
    out.push({ t, label: label(t) });
    if (out.length > 48) break; // safety
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
