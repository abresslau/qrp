# Story: Monitor — FX cross-rate matrix (Bloomberg-FXC-style currency grid)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a markets analyst,
I want a **currency cross-rate matrix** monitor — a grid of the major currencies where each cell is
the cross rate (units of the column currency per 1 unit of the row currency), like the Bloomberg
**FXC / WCRS** screens — with per-currency staleness and an as-of date,
so that I can read every major cross at a glance from QRP's own FX data.

## Background / research (the Bloomberg FX matrix)

Bloomberg's **FXC** ("Currency Rates Matrix") / **WCRS** ("World Currency Rates") show a square grid:
the same set of currencies on the rows and the columns, each cell the **cross rate** between the two
(row = base, column = quote → "quote per 1 base"), the diagonal blank/1.0, with colour and a spot
time/staleness indicator. We reproduce the **functional layout only** (a QRP-native grid over our own
`fx_rate` star), NOT Bloomberg's visual design, branding, or any screenshot.

We can't access a Bloomberg Terminal, so "reproduce" = a QRP page with the same *function*: a square
matrix of major-currency crosses, derived from the warehouse, honest about staleness.

## What QRP already has (reuse — do NOT reinvent)

- **The FX layer** (Epic FX, `packages/sym/src/sym/fx/`): USD-centred star storage in `fx_rate`
  (`base_currency='USD'`, one observed `(quote, as_of_date, source)` row; **inverses and crosses are
  derived, never stored**). ~25 currencies are populated vs USD (EUR/GBP/JPY/CHF/CAD/AUD/NZD/SEK/NOK/
  DKK/HKD/SGD/THB/CZK/HUF/IDR/KRW/MXN/MYR/TRY/CNY/INR/ILS/BRL/TWD), latest ~2026-06-18 (TWD lags — the
  known fawazahmed0 deep-history gap → a real per-currency staleness case).
- **`fx_rate(conn, currency, as_of_date)`** (`fx/resolve.py`) → `FxResolution`: the USD-base rate
  (currency per 1 USD) as-of a date, with **as-of resolution** (latest observed ≤ D; deterministic
  source-rank tiebreak), a tri-state `status` (`ok`/`stale`/`no_data`), `days_stale`, `observed_date`,
  and `is_filled`. USD resolves to 1. Beyond the 7-day **outage cap** → `stale` (rate withheld, never
  fabricated). This is the single primitive the matrix is built from.
- **`convert(amt, from_ccy, to_ccy, as_of_date)` / `triangulate(...)`** (`fx/convert.py`): the cross =
  `amount * to_res.rate / from_res.rate` (via the USD pivot). The matrix cell(base→quote) = the same
  ratio `quote_rate / base_rate`. **Compute one `fx_rate` per currency (N calls), then derive the
  N×N grid by division — do NOT make N² DB calls.**
- **The sym gateway/router** (`services/api/src/qrp_api/modules/sym/{gateway,router}.py`): the sym DB
  holds `fx_rate`, so an FX-matrix endpoint belongs here, mirroring `index_board()` (and its optional
  `as_of_date` query param, `as_of_date` canonical naming, the read-only pattern).
- **The Monitor area** (`apps/web/app/monitor/`, `lib/nav.ts` `MONITOR_SUBNAV`): add a new subpage
  (e.g. `/monitor/fx`, label "FX matrix" / "Currencies"). Reuse the WEI page's idioms — the as-of date
  picker (default latest, `as_of_date` query), the per-row stale ● + tooltip, SSR-safe `react-hooks`
  newest-wins fetch, honest empty state.

## Acceptance Criteria

1. **A matrix endpoint.** `GET /api/sym/fx/matrix` returns, for a curated set of major currencies (the
   columns/rows, ordered), a square grid where `cell(base, quote)` = units of `quote` per 1 `base`
   (= `quote_rate / base_rate` from `fx_rate`), the **diagonal = 1.0**. Read-only; one `fx_rate`
   resolution per currency (N calls), grid derived by division (no N²). Optional `as_of_date` query
   param backdates the whole matrix (omitted ⇒ latest); the canonical name is `as_of_date`; a bad value
   is a 422. An optional `currencies` param (CSV) overrides the default set.
2. **Per-currency freshness, honestly.** Each currency carries its `fx_rate` `status`
   (`ok`/`stale`/`no_data`), `observed_date`, and `days_stale`/`is_filled`. A cell whose **base or quote
   leg** is not `ok` (stale/no_data) has a **null rate** (never a fabricated cross) and is marked. The
   matrix never forward-fills beyond the outage cap. Header shows the effective as-of date.
3. **The matrix page.** A new Monitor route (added to `MONITOR_SUBNAV`, e.g. `/monitor/fx`, label "FX
   matrix") rendering the grid: row + column headers = currency codes, each cell the formatted cross
   rate (FX precision: ~2 dp for JPY/HUF/KRW/IDR-quoted pairs, ~4 dp otherwise — document the rule),
   the diagonal shaded/blank, stale legs marked (● + tooltip naming the lagging currency + its observed
   date). SSR-safe, dark-mode aware, no new dependency.
4. **As-of control.** A date picker (mirror the WEI page) defaulting to the latest available FX date,
   refetching `?as_of_date=`; a "Latest" reset; the header reflects the effective date; future/empty ⇒
   latest. Per-currency staleness still marked relative to the chosen date.
5. **Honest empty / partial state.** If no FX data exists (or the chosen date predates all of it), an
   honest empty state (not an error). If only some currencies resolve, render the grid with the
   resolved ones and mark the rest — never blank the whole board on one stale currency.
6. **No regression.** The FX layer (`fx_rate`/`convert` semantics, the `fx_rate` constraints, the
   USD-star/derive-don't-store invariant), the existing Monitor pages, and all suites stay green.
   `ruff`/`tsc`/`eslint`/`vitest` clean.
7. **Tests.** (a) gateway `fx_matrix()` from a fake conn: cross = quote/base, diagonal 1.0, a stale leg
   → null cell + flag, currency ordering, `as_of_date` honored; (b) route exists + shape + 422 on a bad
   date; (c) web: the matrix renders the grid + a stale marker + the as-of header from a fixture
   (vitest, SSR-safe).

## Tasks / Subtasks

- [x] Task 1: Gateway `fx_matrix(currencies=None, as_of_date=None)` — one `fx_rate` resolution per
  currency, grid by division (no N²); cell = quote_rate/base_rate (both per-USD), diagonal 1.0, a leg
  not-ok → null cell + stale flag, `is_filled` leg → cell flagged but rate kept; default set
  `DEFAULT_FX_MATRIX` (USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, CNY, BRL); omitted as-of ⇒ latest
  `max(as_of_date)`. Returns as_of_date + currencies + per-currency meta {status, observed_date,
  days_stale} + rows.
- [x] Task 2: Route `GET /api/sym/fx/matrix` — optional `as_of_date: date|None` (422 on bad) +
  `currencies` CSV; `FxMatrix`/`FxMatrixRow`/`FxCell`/`FxCurrencyMeta` models; read pattern mirrors `index_board`.
- [x] Task 3: `app/monitor/fx/page.tsx` + `MONITOR_SUBNAV` "FX matrix" entry — square grid (base\quote
  headers, formatted crosses with JPY/HUF/KRW/IDR-quoted at 2 dp else 4 dp, shaded "—" diagonal,
  per-currency ● header marker + per-cell stale ●), as-of picker (latest default + bounded max + reset +
  effective-date header; picking latest keeps the clean URL), honest empty state.
- [x] Task 4: Verify — 156 api + 121 web tests green; ruff/tsc/eslint clean. Live `/api/sym/fx/matrix`:
  diagonal 1.0, USD→EUR 0.8725, EUR→JPY 184.44 (= USD→JPY/USD→EUR), EUR→USD = 1/0.8725 — cross-consistent.
  Real-Chrome CDP `/monitor/fx`: "FX matrix" in the rail, 10×10 grid, USD/USD "—", USD→EUR 0.8725,
  "EOD · as of 2026-06-18".

## Dev Notes

### Where this fits
A frontend grid + one read endpoint over the existing FX star. No new ingestion, no migration — the
crosses are *derived* from `fx_rate` exactly as `convert()` does (USD pivot). The matrix is the FX
sibling of the WEI board: same Monitor area, same as-of/staleness/honesty idioms, different data.

### Critical conventions (regressions if violated)
- **Derive, never store** — crosses/inverses are computed from the USD-base `fx_rate` rows; the matrix
  must not write anything (read-only) and must not persist a synthetic cross.
- **As-of resolution + staleness** — value for date D = latest observed ≤ D; beyond the outage cap →
  withhold + flag (`stale`), never fabricate/forward-fill past it. `no_data` ≠ `stale`. Per-currency
  recency (TWD lags) — mark it; never imply a single global "today" [memory `freshness_per_market`].
- **Canonical `as_of_date`** everywhere (param/var) — never asof/today/date [memory `as_of_date_canonical_name`].
- **Cross direction** — cell(base, quote) = quote per 1 base = `quote_rate / base_rate` (both "per USD").
  Document it on the page so the read is unambiguous; the inverse cell is its reciprocal.
- **One `fx_rate` per currency, grid by division** — N resolutions, not N² (perf + a single consistent
  as-of snapshot).
- **Read-only API**, no new dependency, SSR-safe + `react-hooks` newest-wins fetch; **no Bloomberg IP**
  (functional reproduction in QRP's own design). Verify via headless Chrome/CDP [memory `minimize_dev_churn`].

### Project Structure Notes
- New: `apps/web/app/monitor/fx/page.tsx`; `MONITOR_SUBNAV` entry in `apps/web/lib/nav.ts`.
- Touch: `services/api/src/qrp_api/modules/sym/gateway.py` (`fx_matrix`), `.../sym/router.py`
  (`/fx/matrix` + models), tests `services/api/tests/` + `apps/web/__tests__/`.
- No migration, no new backend module — read-only over the sym DB's `fx_rate`.

### References
- [Source: packages/sym/src/sym/fx/resolve.py] — `fx_rate`, `FxResolution`, `classify`, OUTAGE_CAP_DAYS.
- [Source: packages/sym/src/sym/fx/convert.py] — `convert`/`triangulate` (the cross = quote/base via USD).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py] — `index_board()` (mirror: as_of_date, read pattern).
- [Source: apps/web/app/monitor/wei/page.tsx] — as-of picker, stale markers, fetch guard to mirror.
- [Source: apps/web/lib/nav.ts] — `MONITOR_SUBNAV` (add the FX entry).
- [Source: _bmad-output/planning-artifacts/epics-fx.md] — USD-star, canonical direction, as-of + staleness, FR7/FR8.
- [Source: memory feedback_as_of_date_canonical_name, feedback_freshness_per_market, feedback_minimize_dev_churn].

## Follow-ups (named, not yet built)
- **Forwards & fixings** — the grids are labelled **Spot** explicitly; Bloomberg FXC has Spot/Forward/Fixing
  tabs. A forwards grid (and fixings) is a planned future addition (Andre, 2026-06-21).

## Open Questions (for Andre — defaults chosen, do not block)
1. **Currency set:** default = G10 majors (USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD) + maybe CNY/BRL. Want
   the full ~25 populated set, a selectable list, or a fixed major grid? (A big grid gets dense fast.)
2. **Cell content:** default = the cross rate only. Add a small daily %-change per cell (needs the prior
   session's cross too) or keep it spot-only for v1?
3. **Direction convention:** default = row=base, column=quote ("quote per 1 base"). Flip if you prefer
   the opposite reading.
4. **Live vs EOD:** v1 is EOD (the FX star is daily). A live/intraday FX mode is a follow-up.

## Dev Agent Record

### Completion Notes
- The whole feature derives from the existing USD-base `fx_rate` star — **one as-of resolution per
  currency, then the N×N grid by division** (cell = `quote.rate / base.rate`). No N² DB calls, no new
  ingestion, no migration, nothing written (derive-don't-store honored).
- **As-of honesty**: a currency whose `fx_rate` status is `stale`/`no_data` yields **null cells**
  (never a fabricated cross); an `is_filled` (carried-forward but within the outage cap) leg keeps its
  rate but flags the cell. Per-currency staleness drives the row/col header ● marker — the TWD-style
  lag surfaces. Omitted `as_of_date` ⇒ the latest FX date; backdating re-resolves the whole grid.
- Mirrors the WEI/Monitor idioms (as-of picker + Latest reset + effective-date header, newest-wins
  fetch, honest empty state, no Bloomberg IP).

### File List
- `services/api/src/qrp_api/modules/sym/gateway.py` (modified — `fx_matrix()` + `DEFAULT_FX_MATRIX`)
- `services/api/src/qrp_api/modules/sym/router.py` (modified — `/fx/matrix` + FxMatrix/Row/Cell/Meta models)
- `services/api/tests/test_fx_matrix_route.py` (new — gateway cross/diagonal/stale + route shape/422)
- `apps/web/app/monitor/fx/page.tsx` (new — the matrix page)
- `apps/web/__tests__/fx-matrix-page.test.tsx` (new — grid/stale/backdate/empty)
- `apps/web/lib/nav.ts` (modified — "FX matrix" MONITOR_SUBNAV entry)

## Change Log
| Date | Change |
|---|---|
| 2026-06-21 | Match Bloomberg FXC orientation (per Andre + the FXC png). DEFAULT is now **column = base** — a cell is the ROW currency per 1 COLUMN currency, so the conventional majors read in their standard direction (USD-row/EUR-col = 1.1461 = EUR/USD; JPY-row/USD-col = USD/JPY). My data already holds the full directional NxN grid, so "column = base" is a transpose of the cell *lookup* (`cellOf(base, quote)`), no value inversion. Added a **Base** control (columns ⟷ rows) to flip the base axis. Replaced the symmetric "Conventional" toggle (which didn't match FXC). Cell tooltip shows the conventional pair (e.g. "EUR/USD"). Default + EUR/USD value CDP-verified live; the Base flip is unit-tested (CDP can't drive a controlled select). 160 api + 123 web green; ruff/tsc/eslint clean. |
| 2026-06-21 | Quoting convention + 2nd table (post-dev refinements, per Andre + the FX convention ref). (1) New `sym/fx/convention.py` — `QUOTE_RANK` seniority map (EUR>GBP>AUD>NZD>USD>CAD>CHF>CNY>BRL>JPY) + `conventional_pair()`; surfaced as `quote_rank` per currency + a conventional `pair` per cell in `/api/sym/fx/matrix`. So GBP/USD, EUR/USD, USD/JPY, **USD/BRL** (standard: USD is base for BRL — config-overridable). (2) "Conventional quotes" toggle on the page orients each cell to its market-standard direction (off = raw row→col). (3) A second **Daily % change** matrix below the rate grid (same heat colouring + orientation). USD moved to the bottom row/column earlier. 160 api + 123 web tests green; ruff/tsc/eslint clean; CDP verified (2 tables, toggle flips orientation). |
| 2026-06-21 | Heat map (post-dev refinement, per Andre — the Bloomberg FXC grid is colour-coded): each cell now carries `chg` = the cross's day-on-day move (gateway resolves each currency's prior observation too — 2N resolutions, still no N²); the page shades cells green/red by the move, opacity scaled by magnitude (0.5%/1%/2% buckets), with a `BASE/QUOTE rate · ±x.xx% 1d` tooltip. `FxCell.chg` added. Live: USD→EUR +1.13%, EUR→JPY −0.74%; CDP shows 45 green / 45 red (anti-symmetric). Tests updated (gateway chg math + page colour). Still in review. |
| 2026-06-21 | Dev complete → review. `fx_matrix()` gateway (N fx_rate resolutions + grid by division, diagonal 1.0, stale-leg → null cell) + `GET /api/sym/fx/matrix` (as_of_date/currencies params) + `/monitor/fx` page (square grid, per-currency staleness, as-of picker) + "FX matrix" subnav. 156 api + 121 web tests green; ruff/tsc/eslint clean; live + real-Chrome CDP verified (cross-consistent). |
| 2026-06-21 | Created story: FX cross-rate matrix monitor — a Bloomberg-FXC-style square grid of major-currency crosses derived from the USD-base `fx_rate` star (cell = quote/base via the USD pivot, diagonal 1.0), per-currency as-of staleness, an as-of date picker. New `GET /api/sym/fx/matrix` (N resolutions, grid by division) + new `/monitor/fx` page. Functional reproduction only (no Bloomberg IP); derive-don't-store + as-of honesty; reuses the WEI/Monitor idioms. Status → ready-for-dev. |
