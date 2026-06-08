---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'Storing benchmark index level/close series (S&P 500, S&P 500 NTR, MSCI World, IBOV, …) with a durable internal identity, so security/universe returns can be compared to benchmarks and alpha computed'
session_goals: 'Design the data model (index levels, separate from prices_raw), the identity scheme (internal sym_id spanning all instrument types; composite_figi as one optional external id), and sourcing (Yahoo + MSCI + others); then apply.'
selected_approach: 'user-selected -> run-all + apply'
techniques_used: ['mind-mapping', 'morphological-analysis', 'reversal-inversion', 'what-if-scenarios', 'five-whys', 'analogical-thinking', 'resource-constraints', 'provocation']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Andre
**Date:** 2026-06-07

## Session Overview

**Topic:** Store benchmark **index level series** (S&P 500, S&P 500 NTR, MSCI World, IBOV, …) so returns can be compared and **alpha** computed.

**Goals:** data model for index levels (not `prices_raw`); a durable internal **`sym_id`** spanning all instrument types (composite_figi demoted to one optional external id); sourcing (Yahoo + MSCI). User directive: **run all techniques, then apply changes.**

## Technique Sweep (divergent)

### Mind Mapping — the territory
Identity ↔ instrument kinds (equity, index, later: FX, rates, ETF, future) · index levels (PR/NTR/GTR variants, currency, calendar) · sourcing (Yahoo, MSCI file, Bloomberg/OpenFIGI, manual) · returns (index returns like fact_returns) · alpha (security/universe return − benchmark return) · attach a benchmark *to* a universe.

### Morphological Analysis — the design dimensions × options
- **Internal id:** bigint identity · prefixed text (`IX…`/`EQ…`) · UUID · reuse composite_figi. → **bigint `sym_id`** (collision-free, never reused, FK-friendly).
- **Equity↔sym_id:** big-bang re-key all tables · **additive 1:1 map (instrument row per security, composite_figi as xref)** · ignore. → additive (non-destructive, reconstructable; broaden later).
- **External ids:** one nullable column each · **`instrument_xref` (sym_id, source, value)** key-value. → xref table (open-ended: composite_figi, yahoo, msci, isin, figi…).
- **Index level store:** in prices_raw · **dedicated `index_levels` (sym_id, session_date, variant, level)** · one table per variant. → dedicated, variant-tagged, close/level-only.
- **Variant modelling:** column per variant · **`variant` row dimension (PR/NTR/GTR)**. → row dimension (extensible, sparse-friendly — Yahoo gives PR+TR, MSCI gives NTR/GTR).
- **Index returns:** recompute in fact_returns · **separate `fact_index_returns` / view from levels**. → separate (levels need no split/dividend math — return = level ratio).

### Reversal/Inversion — "how would we GUARANTEE this fails?"
Cram index levels into prices_raw → split/dividend logic corrupts them; conflate PR vs NTR → silently wrong alpha; key indexes on composite_figi → MSCI has none → can't store them; no internal id → every new instrument type reopens the identity question. ⇒ every failure mode argues for: separate store, explicit variant, internal sym_id, xref.

### What-If Scenarios
- *What if an index has no Yahoo symbol and no FIGI (MSCI)?* → sym_id + `instrument_xref(source='msci', value=code)`; level loaded from a downloaded file. Identity must NOT require any external id.
- *What if Yahoo gives both ^GSPC (PR) and ^SP500TR (TR)?* → two variants under the *same* index instrument (same sym_id), or two instruments? → **same instrument, variant dimension** (they're the same index, different return treatment).
- *What if we later add bonds/FX/crypto?* → `instrument.kind` extends; sym_id already universal.
- *What if a benchmark is in a different currency than the portfolio?* → store index currency; alpha/compare in a stated currency (FX out of scope now, flagged).

### Five Whys — why a sym_id at all?
Compare returns → need a benchmark series → benchmark needs identity → composite_figi doesn't cover indexes/MSCI → need an identity that's independent of any vendor → **internal surrogate `sym_id`, vendor ids as xrefs.**

### Analogical Thinking
Like a **CRSP PERMNO / Bloomberg's internal id / a data-warehouse surrogate key**: a stable internal key that outlives ticker/vendor churn; natural/business keys (FIGI, ISIN, Yahoo sym) hang off it. Equities already have this in spirit (composite_figi) — `sym_id` generalizes it to all instrument kinds.

### Resource Constraints — smallest thing that delivers value now
A `benchmark`-flavored instrument + `index_levels` + a Yahoo level fetch for ~6 headline benchmarks + index returns = immediately compare a universe's return to S&P 500 / NTR and compute alpha. MSCI/file-load + FK-broadening are fast-follows.

### Provocation — "indexes ARE securities; treat them identically"
Tempting (reuse everything) but false: no shares, no splits, no OHLCV, PR/NTR variants, vendor-less identity. The *identity spine* (sym_id) is shared; the *data model* (levels vs OHLCV) is not. ⇒ shared instrument registry, separate price-vs-level stores.

## Convergence — the design to apply

1. **`instrument`** — universal identity: `sym_id` (BIGINT identity PK), `kind` ∈ {equity, index, …}, `name`, `currency_code` (nullable), `status`, timestamps. The canonical spine for everything going forward.
2. **`instrument_xref`** — `(sym_id, source, value)` open-ended external ids: `composite_figi`, `yahoo`, `msci`, `isin`, `figi`, … (source-tagged, unique per (source,value)).
3. **Equity backfill (additive, non-destructive):** one `instrument(kind='equity')` per existing `securities` row, with xref `composite_figi`. Existing equity/price/returns/universe tables keep `composite_figi` — `sym_id` ↔ `composite_figi` via xref. (Future option: broaden FKs to `sym_id`; not now.)
4. **`index_levels`** — `(sym_id, session_date, variant ∈ {PR,NTR,GTR}, level, source)`, close/level only, immutable (ON CONFLICT DO NOTHING), source-tagged. PK `(sym_id, session_date, variant)`.
5. **Sourcing:** a Yahoo index-level adapter + a benchmark registry (`^GSPC`→S&P500/PR, `^SP500TR`→S&P500/NTR-ish, `^IXIC`, `^DJI`, `^STOXX50E`, `^BVSP`→IBOV, …); MSCI = `instrument_xref(source='msci')` + file load (deferred); OpenFIGI index FIGIs as an *optional* xref only (don't depend on it).
6. **Returns/alpha:** index returns computed from level ratios (no split/dividend math) over the same windows; **alpha = security/universe return − benchmark return** (excess), computed at query time / via a helper. Attach a default benchmark to a universe (config) as a fast-follow.

## Apply plan (additive, reconstructable — migrations + git)
B1 identity layer (`instrument`, `instrument_xref`) + equity backfill · B2 `index_levels` + Yahoo level sourcing + populate headline benchmarks · B3 index returns + alpha helper + CLI. Each: migration triplet + code + DB-free tests + live verify + commit.

## Outcome — APPLIED (2026-06-07)

All three shipped (migrations + code + tests + commits; stories `B1`/`B2`/`B3` in implementation-artifacts):
- **B1** `instrument` + `instrument_xref` (universal `sym_id`, vendor ids as one-to-many xrefs, `UNIQUE(source,value)` so each external id → one instrument). 2,047 equities backfilled 1:1.
- **B2** `index_levels` (PR/NTR/GTR, level-only, immutable). **94,930 levels** across 11 Yahoo benchmarks; MSCI World deferred (msci xref, file import next).
- **B3** `fact_index_returns` (level ratios over the 18 windows) + `alpha = asset − benchmark`. Live: **Apple +13.45% alpha vs S&P 500 TR (10Y ann.)**.

Fast-follows (not done): MSCI file import for NTR/GTR series; attach a default benchmark to a universe; broaden equity FKs onto `sym_id` (currently additive via xref). OpenFIGI-for-indexes confirmed *optional* (don't depend on it) — `sym_id` + yahoo/msci xref is the spine.
