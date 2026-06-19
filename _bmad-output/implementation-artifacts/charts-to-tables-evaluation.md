# Evaluation: which console charts should be tables?

Status: evaluation (2026-06-19) · Operator: "most of the charts look terrible, evaluate what could be table."

## Method

Audited every visualization in `apps/web` (component, file, implementation, data, page) and judged each
against the rule: **a chart earns its space only when a pattern/shape matters; precise small/single-series
data is clearer as a table** (optionally with an in-row sparkline).

## Finding (honest, and a little surprising)

**The charts are mostly justified — there is no library debt and few clear table-conversions.** Every
chart is hand-rolled SVG (no recharts/visx/nivo/chart.js; only `d3-hierarchy` for the treemap), and the
prior author already used tables for precise/ranked/sparse data and charts only for trend/shape. So the
"charts look terrible" reaction is likely **visual polish** (cramped axes, weak labels, thin lines,
color/contrast), not "should be a table." The recommendations below split into *convert* (few) and
*polish* (most).

## Inventory + verdict

| Visualization | File:lines | Impl | Data | Verdict |
|---|---|---|---|---|
| Heatmap treemap | `components/heatmap-view.tsx:307-387` | SVG + d3-hierarchy | universe by mkt-cap, colored by return | **Keep** — 50-500 cells, sector concentration is the value |
| Macro featured line | `components/macro-browser.tsx:274-378` | hand SVG line+area | a macro series ± overlay (actual vs Focus) | **Keep** — multi-year trend + actual/forecast gap |
| Macro comparison multi-line | `components/macro-compare.tsx:196-232` | hand SVG multi-line | 2-8 comparable series across countries | **Keep** — cross-country divergence is the point |
| Backtest equity curve | `app/backtest/page.tsx:23-67` | hand SVG dual-line | strategy vs baseline, daily | **Keep** — drawdown/recovery shape |
| Optimiser weights bar | `app/optimiser/page.tsx:334-340` | inline div bars | per-holding allocation | **Keep** — concentration scan; exact % in adjacent column |
| **Alt-data series chart** | `app/altdata/page.tsx:23-52` | hand SVG polyline | single series, 2-500+ pts | **Convert/adapt** — a 2-5 point series is a bad chart; render `<48` pts as an in-row **sparkline + last/Δ table**, only `>48` as the line |
| Macro research sparkline | `macro-browser.tsx:170-191` | SVG polyline (120×28) | last 48 obs, in-table | **Keep** — already the right pattern (sparkline-in-table) |
| Analytics metrics grid | `analytics-panel.tsx:156-228` | HTML cards | 15 risk KPIs | **Already a table** (cards) — fine |
| Signals / backtest-runs / optimiser-solutions / portfolio-contributions | various | HTML tables | rankings / sparse dims | **Already tables** — correct |
| api-status dot, sidebar chevron | components | tiny SVG | UI state | **Keep** — icons, not data |

## Recommendations (prioritized)

1. **Polish pass on the 4 kept charts (highest impact on "looks terrible").** A small shared SVG-chart
   helper would fix the cross-cutting issues at once: consistent margins/padding, axis ticks + labels
   (many currently have none), a baseline/zero line, hover crosshair + value readout, dark-mode-aware
   stroke/grid, and a min-height so sparse series don't look broken. This is almost certainly what the
   operator is reacting to — the charts are *bare*, not *wrong*. (Est: one `components/chart.tsx`
   primitive + adopt in the 4.)
2. **Alt-data series → adaptive (table+sparkline below a threshold).** A 3-point pageviews "chart" should
   be a "last value · range · sparkline" row, not a stretched line. Convert `<48` pts to the macro
   sparkline-in-table pattern that already exists.
3. **Consider one charting primitive vs hand-rolling.** Not urgent, but if more charts are coming, a
   single internal `<LineChart>`/`<Sparkline>` (still SVG, no heavy dep) removes the per-chart
   re-implementation and makes the polish consistent. A library (recharts/visx) is only worth it if
   chart count grows a lot — for now a ~150-line internal primitive is the right call (keeps the
   self-contained ethos).

## Bottom line

Don't mass-convert charts to tables — the data/altitude split is sound. The win is **(a) a polish pass via
a shared SVG primitive** (axes/labels/zero-line/dark-mode/min-height) and **(b) making the alt-data series
adaptive**. If the operator still wants specific charts as tables after the polish, that's a per-chart
call — but the audit says the current chart-vs-table choices are defensible.
