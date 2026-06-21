// Shared date-axis ticks for the platform's SVG time-series charts — matplotlib-style.
//
// Instead of the first/last date (or N points linearly between them), pick "nice" round tick
// locations adapted to the span: year boundaries for multi-year ranges (2002, 2004, …), month
// boundaries for months (Jan '24, Apr '24, …), day boundaries for short ranges (Jun 1, Jun 8, …).
// Tick times are returned as ms epoch; the chart maps them through its own x-scale.
//
// Dates in this platform are date-only ISO strings (UTC midnight), so everything is computed and
// formatted in UTC to avoid a timezone day-shift.

export type AxisTick = { t: number; label: string };

const DAY = 86_400_000;

// Smallest "nice" multiple ≥ rough, from the given ladder (matplotlib-ish).
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

/** Adaptive single-date label (kept for callers that format an arbitrary time, e.g. a hover). */
export function fmtAxisDate(t: number, spanDays: number): string {
  if (spanDays > 365 * 2.5) return yearLabel(t);
  return spanDays > 75 ? monthLabel(t) : dayLabel(t);
}

/**
 * "Nice" date ticks across [minT, maxT] (ms epoch), aiming for ~`target` ticks at round
 * boundaries. Returns [] for a non-positive span.
 */
export function dateAxisTicks(minT: number, maxT: number, target = 6): AxisTick[] {
  if (!(maxT > minT)) return [];
  const spanDays = (maxT - minT) / DAY;
  const out: AxisTick[] = [];

  if (spanDays > 365 * 1.5) {
    // YEAR ticks at Jan 1 of every `step`-th year.
    const step = niceStep(spanDays / 365.25 / target, [1, 2, 5, 10, 25, 50, 100]);
    const startYear = Math.ceil(new Date(minT).getUTCFullYear() / step) * step;
    for (let y = startYear; ; y += step) {
      const t = Date.UTC(y, 0, 1);
      if (t > maxT) break;
      if (t >= minT) out.push({ t, label: yearLabel(t) });
    }
  } else if (spanDays > 70) {
    // MONTH ticks at the 1st of every `step`-th month (aligned to the calendar year).
    const step = niceStep(spanDays / 30.44 / target, [1, 2, 3, 6]);
    const d0 = new Date(minT);
    let y = d0.getUTCFullYear();
    const mi = Math.ceil(d0.getUTCMonth() / step) * step; // month index aligned to step
    y += Math.floor(mi / 12);
    let m = mi % 12;
    for (;;) {
      const t = Date.UTC(y, m, 1);
      if (t > maxT) break;
      if (t >= minT) out.push({ t, label: monthLabel(t) });
      m += step;
      while (m >= 12) {
        m -= 12;
        y += 1;
      }
    }
  } else {
    // DAY ticks at midnight boundaries every `step` days.
    const step = niceStep(spanDays / target, [1, 2, 5, 7, 14, 28]);
    const start = Math.ceil(minT / DAY) * DAY;
    for (let t = start; t <= maxT; t += step * DAY) out.push({ t, label: dayLabel(t) });
  }

  // Degenerate fallback (e.g. a sub-step span produced <2 boundaries): two adaptive ends.
  if (out.length < 2) {
    return [minT, maxT].map((t) => ({ t, label: fmtAxisDate(t, spanDays) }));
  }
  return out;
}
