# `rates` package — maintenance plan (UK yield curves)

Per QRP's index/data maintenance-plan discipline: source, format, cadence, history, gating, PIT
boundary, conventions, licence — all **probed in-env 2026-06-22** before building.

## Source

**Bank of England — daily UK yield curves** (Monetary & Financial Conditions Division).

- Landing page: `https://www.bankofengland.co.uk/statistics/yield-curves` (probed: HTTP 200).
- Download base: `https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/`
- **Latest bundle (daily/tail load):** `latest-yield-curve-data.zip` — current-month daily files
  (4 xlsx: GLC Nominal/Real/Inflation + OIS). Probed: HTTP 200, ~373 KB.
- **Full history (backfill):** `glcnominalddata.zip` (~39 MB), `glcrealddata.zip`,
  `glcinflationddata.zip`, `oisddata.zip`. (Monthly archives `*monthedata.zip` and the commercial
  `blc*` curves also exist — `blc` is out of v1.)

## Format (probed)

Each xlsx has sheets: `info`, `1. fwds, short end`, `2. fwd curve`, `3. spot, short end`,
`4. spot curve`.

- The `info` sheet carries provenance ("Sources: Bloomberg Finance L.P., Tradeweb and Bank
  calculations") and revision notes.
- A curve sheet's row with `years:` in column A holds the **tenor grid** (years); each subsequent
  row is `<date>, v(t0), v(t1), …`. **Values are % per annum** (real can be **negative**). The date
  in column A is the curve's stated date → `as_of_date` (never the ingest date).

### Dimensions found (drives the `curve_point` schema)

| curve_set | basis | rate_type | tenor grid (curve sheet) |
|---|---|---|---|
| `glc` (gilt) | nominal | spot, forward | 0.5–40y (0.5y steps) |
| `glc` | real | spot, forward | 2.5–40y |
| `glc` | inflation | spot, forward | 2.5–40y |
| `ois` | nominal | spot, forward | 0.5–25y |

- **There is NO `par` curve** (the brainstorm assumed spot/forward/par; BoE publishes only **spot +
  forward**). Schema `rate_type` is therefore `{spot, forward}` — the story/schema were reconciled to
  this finding (the reconciliation guard is inflation = nominal − real, plus a forward↔spot
  diagnostic, rather than par↔spot).
- Two tenor-grid resolutions per file: the canonical **curve** grid (0.5y steps) and a finer
  **short end** grid (monthly, sub-year). The parser keeps both (curve wins on shared tenors;
  short-end-only sub-year nodes are added) — tenor is stored as data, not columns.
- Inflation is **RPI-based with the linker indexation lag** — labelled `inflation`, never CPI.

## Conventions

BoE fits/bootstraps and publishes the curve; we store it verbatim and derive on read. The compounding +
day-count are **pinned from the BoE yield-curve FAQ** (the methodology accordion on the statistics/
yield-curves page, read in-env 2026-06-22 — authoritative):

- **Compounding:** *"The yields (spot and forward) are continuously compounded and quoted on an annual
  basis."* → a published zero/spot rate `s(t)` (% p.a.) gives the discount factor
  **`DF(t) = exp(-s(t)/100 · t)`** with `t` in years; the instantaneous forward `f` satisfies the
  continuous-compounding identity **`s(t)·t = ∫₀ᵗ f(u) du`** (so `spot(t)` = the average instantaneous
  forward over `[0,t]`).
- **Day count:** *"For UK government bonds … Actual/Actual since November 1998 (Actual/365 prior). For all
  other instruments the convention is Actual/365."* The published curve nodes are already annualised
  (tenor = years), so curve-level discounting uses `DF=exp(-s·t)` directly; day-count only matters when a
  *specific instrument's* cashflow dates are converted to year fractions (gilt ACT/ACT, else ACT/365) —
  relevant to the DV01/PV helper over a dated cashflow schedule.

Consequence: the derive-on-read forward↔spot reconciliation is now the **exact** continuous-compounding
identity (FAIL-level), not an assumed/approximate WARN — the only residual is trapezoidal discretization
over the published tenor grid (measured ~0.02pp median, ~0.36pp max on the 0.5y grid; the FAIL tolerance
sits above that). `inflation = nominal − real` remains the exact FAIL-level free check.

## Cadence / schedule

Daily, after BoE's London-time publish. Scheduled (Dagster, STOPPED until enabled):
`rates_curve_daily` — `15 17 * * 1-5`, **`execution_timezone="Europe/London"`** (explicit, DST-aware)
→ runs `rates curve load` then `rates validate`.

## History

Full published daily history is in the per-curve archive zips (nominal back to ~1979/2016 for 40y;
real/inflation from later). `rates curve load --start_date …` pulls the archives; the tail load uses
the latest bundle.

## Gating / PIT boundary

- **Plausibility:** a day-over-day move > 5.0pp for a tenor routes to `rates.curve_point_review`
  (never lands silently).
- **Atomic per-day** insert; the **tail** load gates (skips) a day missing the expected basis set
  (a desynced/premature current-day publish); **backfill** inserts legitimately-partial history.
- **Two vintages:** `first_value` (immutable first-published) + `value` (restated latest). Reads
  default to latest; a backtest reads `first_value` (PIT). `last_changed_at` re-stamps only on a
  real restatement.
- **Stale gating:** `rates validate` warns when the latest curve is > 1 business day old (UK
  weekends excluded).

## Licence

Bank of England yield-curve data is **Open Government Licence** (free reuse with attribution) — a
compliance advantage over a vendor feed (no redistribution restriction). Attribute BoE as the source.

## Re-test trigger

The host was reachable in-env 2026-06-22 (latest bundle parsed end-to-end). If `rates curve load`
starts returning 0 inserts or a `CurveLayoutError`, re-probe `latest-yield-curve-data.zip` (URL +
sheet/column layout) — BoE occasionally restructures the workbook (the parser asserts layout and
fails loud rather than mis-mapping).
