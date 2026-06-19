# World Map Visualization for QRP Console Population View

## 1. THE POPULATION PAGE — Identification & Current UI

### Primary Candidate: `/sym/universes` (Universes Coverage Page)

**Path:** `/c/Projects/qrp/apps/web/app/sym/page.tsx` (lines 48–122)  
**Current Title:** "Universes"

This is the plausible "population page" because:
- Displays per-universe coverage of security populations (prices/returns/fundamentals)
- Shows members_resolved (population size) plus coverage counts
- Coverage is per-member and per-layer, respecting market closure times
- Note at line 62: "markets close at different times, so a name a day behind its market isn't counted missing"

### Current UI Rendering

The page renders a table showing:
```
Universe | Members | Prices      | Returns     | Fundamentals
---------|---------|-------------|-------------|---------------
sp500    | 500     | 500/500 (ok)| 500/500 (ok)| 495/500 (partial)
ibov     | 78      | 60/78 (part)| 0/78 (miss) | 78/78 (ok)
```

Status pills per layer at lines 24–26:
- Green (ok) = all members current
- Amber (partial) = some lag/missing
- Red (missing) = none covered

Links to:
- Explorer: /sym/explorer?u={universe_id}
- Heatmap: /sym/heatmap?u={universe_id}

---

## 2. GEOGRAPHIC DATA MODEL

### Core Tables & Join Chain

exchange (line 9–21 in exchange.sql)
├─ mic (CHAR(4)) PRIMARY KEY
├─ name (TEXT)
├─ country (TEXT)
├─ country_iso (CHAR(2)) [ISO 3166-1 alpha-2 code]
├─ timezone (TEXT) [IANA timezone]
└─ currency_code (CHAR(3))

securities (line 11–26 in securities.sql)
├─ composite_figi (CHAR(12)) PRIMARY KEY
├─ mic (CHAR(4)) [FK to exchange.mic]
├─ currency_code (CHAR(3))
└─ status (active|delisted|suspended)

universe_member_resolution (line 12–25 in universe_member_resolution.sql)
├─ universe_id (TEXT)
├─ composite_figi (CHAR(12)) [FK to securities]
└─ resolution_status (resolved|unresolved|unpriced)

### Join Pattern for World Map (demonstrated in gateway.py lines 558–587)

The securities endpoint already shows this join:

SELECT ex.country, ex.country_iso, s.composite_figi, ...
FROM universe_member_resolution r
JOIN securities s ON s.composite_figi = r.composite_figi
LEFT JOIN exchange ex ON ex.mic = s.mic
WHERE r.universe_id = %s AND r.resolution_status = 'resolved'

---

## 3. VISUALIZATION PATTERNS — Stack to Match

### Component: heatmap-view.tsx (1–457 lines)

**Libraries used:**
- d3-hierarchy v3.1.2 (only this, not full d3)
- Hand-rolled SVG via React

**Key code patterns:**

Dark mode hook (lines 70–81):
- Observes HTML class="dark" toggle
- Switches neutral colors: light (228,228,231) vs dark (42,42,48)

SVG rendering (lines 307–386):
- hierarchy() + treemap() + treemapSquarify algorithm
- Color via rgbFor(ret, isDark) function
- Hover tooltips with absolute positioning and viewport clamping
- Adaptive font sizing based on tile dimensions

**Why no external map library:**
- Minimalism: only d3-hierarchy, no Mapbox/Leaflet overhead
- Control: owns the SVG rendering layer (styling, dark mode, interactivity)
- Philosophy: "render React + SVG, own the color logic"

---

## 4. MARKETS CLOSE AT DIFFERENT TIMES — Freshness & Timezone

### Freshness Model (freshness.py lines 1–45)

STALE_AFTER_DAYS = 4

AreaFreshness dataclass tracks:
- area: prices|returns|fundamentals
- as_of_date: date or None
- days_behind: int vs latest trading session
- status: ok|stale|unknown

classify() returns ok if <= 4 days behind, stale if > 4

### Per-Member Recency Check (gateway.py lines 166–225)

universe_coverage() method uses:

WITH px AS (
  SELECT composite_figi, max(session_date) d FROM prices_raw
   WHERE session_date >= %(latest)s - 14
)
SELECT count(*) FILTER (WHERE px.d >= %(latest)s - 7) AS px_cov

Key: 14-day lookback, 7-day coverage threshold
Rationale: Markets close at different times; a member not trading Fri-Mon is not "missing"

Recency windows by layer (lines 185–190):
- Prices: 7 days
- Returns: 7 days (on one window_id)
- Fundamentals: 180 days (low cadence)

### Timezone Column

exchange.timezone (line 14 in exchange.sql): IANA identifier
e.g., America/New_York, Asia/Tokyo, Europe/London

Used to explain why coverage freshness varies per market.

---

## 5. KEY FILE REFERENCES

| Purpose | Path | Lines | Detail |
|---------|------|-------|--------|
| Population Page | /c/Projects/qrp/apps/web/app/sym/page.tsx | 48–122 | Universes coverage table |
| Exchange Schema | /c/Projects/qrp/packages/sym/migrations/deploy/exchange.sql | 1–29 | MIC, country, country_iso, timezone, currency |
| Securities Schema | /c/Projects/qrp/packages/sym/migrations/deploy/securities.sql | 11–47 | Composite FIGI, MIC FK, currency, status |
| Member Resolution | /c/Projects/qrp/packages/sym/migrations/deploy/universe_member_resolution.sql | 12–25 | Frozen FIGI resolutions, status |
| Heatmap Component | /c/Projects/qrp/apps/web/components/heatmap-view.tsx | 1–457 | D3 treemap, SVG rendering, dark mode, tooltips |
| Coverage Compute | /c/Projects/qrp/services/api/src/qrp_api/modules/sym/gateway.py | 166–225 | universe_coverage() per-member per-layer |
| Freshness Logic | /c/Projects/qrp/services/api/src/qrp_api/modules/sym/freshness.py | 1–45 | Status classification (ok/stale/unknown) |
| Securities Endpoint | /c/Projects/qrp/services/api/src/qrp_api/modules/sym/gateway.py | 495–613 | Demonstrates country/country_iso enrichment |
| Explorer Page | /c/Projects/qrp/apps/web/app/sym/explorer/page.tsx | 1–211 | Shows country_iso per security |
| Web Dependencies | /c/Projects/qrp/apps/web/package.json | 15–20 | Only d3-hierarchy (3.1.2); no recharts/visx |

---

## 6. DESIGN SUMMARY

The Universes Coverage page is the "population page."

World map would:
1. Map members to countries via securities.mic→exchange.country_iso
2. Color countries by coverage (ok/partial/missing) per layer
3. Show timezone context to explain freshness variance
4. Match D3 + hand-rolled SVG pattern (no external map lib)
5. Reuse pill colors and dark-mode palette from heatmap

Data model, API patterns, and viz philosophy are production-ready.
