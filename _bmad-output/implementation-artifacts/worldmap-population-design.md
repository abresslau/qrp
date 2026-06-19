# Design Story: World-map view of the universe population & coverage

Status: ✅ BUILT (2026-06-19). The "population page" is **`macro > population`** (the World Bank
population category), NOT the sym Universes landing — corrected with Andre mid-build. The map there is
a world **demographic** choropleth, not securities coverage.

Shipped:
- `apps/web/lib/world-geo.ts` — vendored, pre-projected ISO-A2 path lookup (Natural Earth 110m, public
  domain), hand-rolled equirectangular, NO runtime map/geo dependency. (Reusable for any choropleth.)
- `apps/web/components/macro-population-map.tsx` + `apps/web/app/macro/population/page.tsx` — a static
  route (overrides `/macro/[category]`) with the world map on top (Total population log-scaled, or
  Growth diverging) + the existing `MacroBrowser` series list below. Hover → population + growth.
  Driven by `/api/macro/series` (category=population, geo→ISO-2 for the 14 mapped economies; Euro-area
  aggregate excluded). Test: `__tests__/macro-population-map.test.tsx`.

Separately (Andre's other ask, kept on sym): coverage now validates ACTIVE members only — delisted
names are excluded from numerator+denominator — and the Universes table shows a Members|Active split.
The first-pass securities by-country map (population-map.tsx + a `coverage_by_country` endpoint) was
REMOVED once "population" landed under macro; only the active-only coverage change stayed.

<!-- Created via bmad overnight 2026-06-19. Operator: "the population page looks terrible, create a
story to come up with design of worldmap." The "population page" = the Universes coverage landing
(apps/web/app/sym/page.tsx) — it's a flat table; the operator wants a world-map visualization. This is
a DESIGN story: it proposes the design + the data/endpoint, to review before building. -->

## The problem

The Universes landing (`/sym`, `app/sym/page.tsx`) is the "population page" — it shows, per universe,
the resolved member count and per-layer (prices/returns/fundamentals) coverage as a flat table of
status pills. It's honest but visually flat, and it **hides the geography**: you can't see that a
universe's gaps cluster in one market, or that "markets close at different times" means Tokyo is a day
behind New York. A **world map** makes the population and its coverage legible at a glance.

## Why a map fits QRP's data

Every security carries a `mic` → `exchange.country` / `country_iso` / `timezone`
(`packages/sym/migrations/deploy/exchange.sql:9-21`), and members resolve via
`universe_member_resolution`. So we can aggregate any universe (or the whole master) **by country**,
and we already compute per-member coverage/recency (`gateway.universe_coverage`, `freshness.py`). The
map is a new *view* of data we already produce — not new data.

## Proposed design

A **choropleth world map** on the Universes landing (replacing or sitting above the current table):

- **Geometry:** countries shaded by a metric. Hand-rolled inline SVG with an embedded world TopoJSON/
  GeoJSON (matches the codebase's "own the SVG layer" philosophy — the heatmap is hand-rolled SVG via
  d3-hierarchy, NO external chart/map lib; see `components/heatmap-view.tsx`). Use a lightweight
  world-countries GeoJSON (ISO-A2 keyed) inlined or served as a static asset; project with
  `d3-geo` (geoNaturalEarth1) — d3-geo is small and consistent with the existing d3-hierarchy use.
- **Two modes (a toggle, mirroring the heatmap's EOD/LIVE toggle):**
  1. **Population** — country shaded by member count (sequential scale); the map answers "where does
     this universe live?" (e.g. S&P 500 = almost all US; an MSCI World = spread).
  2. **Coverage** — country shaded by % of its members current in the selected layer
     (prices/returns/fundamentals), reusing the coverage scale (green=ok / amber=partial / red=gap).
     This is the honest cross-market freshness picture: the US fully green, a lagging market amber.
- **Scope selector:** "All universes" + each universe (reuse the existing universe list); a layer
  selector (prices/returns/fundamentals) for coverage mode.
- **Interaction (mirror the heatmap):** hover a country → tooltip with country name, member count,
  per-layer coverage (covered/total), latest date, and the **exchange timezone(s)** (so "current as of
  2026-06-17 in Asia/Tokyo" explains why it differs from NY). Click a country → Explorer filtered to
  that universe + (future) that country; or click an amber country → the gap names (reuse the new
  `?gap=` drill-down). Dark-mode aware (the heatmap's `useIsDark` + the green/neutral/red palette).
- **Keep the table** below the map as the precise readout (the map is the scan, the table is the
  numbers) — or make the map the hero and the table a collapsible detail.

## Data / API (the only backend work)

One new endpoint mirroring `universe_coverage`, grouped by country instead of (or in addition to)
universe: `GET /api/sym/universes/coverage/by-country?universe=<id|all>` →
`[{country, country_iso, timezone, members, prices:{covered,total,latest}, returns:{…}, fundamentals:{…}}]`.

Reuse the exact index-bounded query shape from `universe_coverage()` (per-figi `max(date)` over a recent
window, returns restricted to one `window_id`) but `GROUP BY ex.country_iso` instead of universe — and
join `universe_member_resolution` only when a universe is selected (else the whole active master). The
join chain is proven (`securities s JOIN exchange ex ON ex.mic = s.mic`, already used in the explorer
enrichment + heatmap). **Heed the 125s lesson:** never `count(DISTINCT)` over `prices_raw`; per-figi
max via the PK, bounded window. Time it (<2s) before shipping.

## Acceptance criteria (for the build story)

1. New `…/coverage/by-country` endpoint (universe-scoped or all), index-bounded, <2s, tested DB-free +
   a perf guard.
2. A hand-rolled SVG choropleth (d3-geo projection, inlined world GeoJSON, dark-mode + tooltip mirroring
   the heatmap), Population + Coverage modes, universe + layer selectors.
3. Country shading from the coverage data; hover tooltip shows members, per-layer coverage, latest
   date, timezone; click → Explorer (universe + gap drill-down).
4. Lives on `/sym` (the population page); the existing coverage table kept as the precise readout.
5. No new heavy dependency beyond `d3-geo` (+ a small world GeoJSON asset, inlined/static); types via
   gen:types; tsc/eslint/build green; console test renders the map + a country shade from a mock.

## Open design questions (for the operator)

1. **Map or table as hero?** Map-first with table below, or a toggle between the two?
2. **Single metric or small-multiples?** One map with a layer selector, or three small maps
   (prices/returns/fundamentals) side by side?
3. **Country granularity vs exchange granularity** — color by country (cleaner) or by exchange/MIC
   (more precise, but multiple exchanges per country)? Country is the cleaner v1.
4. **GeoJSON source** — inline a ~100KB simplified world-countries GeoJSON (no network, matches the
   self-contained ethos) vs a static asset. Recommend inline/static, ISO-A2 keyed.

## References
- `apps/web/app/sym/page.tsx` — current population page (the table to augment).
- `apps/web/components/heatmap-view.tsx` — the hand-rolled SVG + dark-mode + tooltip pattern to mirror.
- `services/api/src/qrp_api/modules/sym/gateway.py` `universe_coverage()` — the coverage query to regroup by country.
- `packages/sym/migrations/deploy/exchange.sql:9-21` — country/country_iso/timezone per MIC.
- [[project_freshness_per_market]] — the per-member-recency rule the map must honor.
