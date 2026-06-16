# Add Nasdaq-100 (`nasdaq100`) as an index universe

Status: in-progress (2026-06-16, autonomous)

## Population log (2026-06-16)

1. ✅ Registered: `sym universe add nasdaq100 --kind index --name "Nasdaq 100" --index nasdaq100 --source-pref wikipedia,fmp`.
2. ✅ Membership refreshed: `appended=510 events, resolved=197, unresolved=71, projected 197 figis / 185 intervals`.
3. ✅ **Membership VERIFIED sound** — the count flag is cleared. `members(conn, "nasdaq100", today)` = **103 current members** (calibration: sp500 = 503). The 197 is the *all-history* resolved set (`members_resolved` counts history, not current); the 71 unresolved are old delisted leavers (expected, not current). So the Wikipedia parse is correct after all — current PIT membership is a clean 103.
4. ✅ Prices: `sym load --scope universe:nasdaq100` → **103/103 loaded, 0 errored, 49,983 rows**.
5. ✅ Fundamentals/market cap: `sym fundamentals --universe nasdaq100` → 194 loaded, market_cap_usd recomputed (8,244 rows).
6. ✅ Returns: `sym recompute` → universe_readiness now PASS (was 89.3%).
7. ✅ `calendar_mic=XNAS` set + `## nasdaq100` plan section added to `docs/universe-maintenance.md` → maintenance_plan_coverage PASS.
8. ✅ GICS: `sym classify` (90% global coverage).
9. ✅ **Heatmap renders nasdaq100** — EOD 1D + LIVE both 200; top tiles NVDA/AAPL/MSFT/AMZN/GOOGL/AVGO; LIVE priced 161/161. `/universes` = 15.

## Final state (functionally DONE; renders in the heatmap)

`sym validate --universe nasdaq100` → 7 pass, 3 warn, **3 fail**. Triaged:

- **NOT caused by this add (pre-existing, global checks):** `unpriced_securities` (42 active-unpriced)
  and `identity_completeness` (41) scan ALL ~2,191 securities, not just nasdaq100. **Confirmed: 0
  current nasdaq100 members are unpriced** (all 103 priced); the flagged names are non-Nasdaq (e.g.
  CMA / Comerica, an NYSE bank). These FAILs predate nasdaq100.
- **nasdaq100-specific:** `universe_member_completeness` — **13 of 103 incomplete: 11 missing `name`
  (metadata for newly-resolved members), 2 missing GICS.** Minor (heatmap falls back to ticker /
  "Unclassified"); not corruption.

### Follow-ups (finisher metadata — for operator review, not blocking the heatmap)

- Backfill `security_names` for the 11 newly-resolved members missing a name (e.g. BBG000GQPB11,
  BBG01H7CZ9S9, …) — name source/step to confirm.
- The 2 missing-GICS members are the **known non-Brazil-GICS gap** (classify is ~90%, b3 fill is
  Brazil-only; SEC SIC→GICS fallback is the ledgered fix) — affects all non-Brazil universes, not
  just nasdaq100.
- (Optional) price the still-listed historical leavers to reduce the global `unpriced_securities`
  count — pre-existing, per the "reload covers leavers" convention.

**Code committed:** `wikipedia.py` spec + this doc + the `universe-maintenance.md` section. The data
(membership/prices/fundamentals/returns) lives in the DB. ruff + 13 provider tests green.


Operator asked: "we should pull nasdaq as universe." We currently pull **no** NASDAQ universe
(14 universes: S&P 500/400/600, FTSE 100, Ibovespa/IBrX, and European flagships). This adds the
**Nasdaq-100** (the tradeable 100-name index) — NOT the Nasdaq Composite (~3000 names, "all
Nasdaq-listed", no curated membership list and far over the live-heatmap cap).

## Maintenance plan (REQUIRED before populating an index universe — project rule)

- **Source (membership):** Wikipedia **"Nasdaq-100"** article → its *Components* table (archetype
  `wikipedia`, keyless). Confirmed reachable + parseable read-only: **114 member tokens** parsed via
  `WikipediaIndexSource.fetch("nasdaq100", …)`. Secondary: FMP `nasdaq` constituent endpoint
  (`fmp.py` already maps `nasdaq100 → "nasdaq"`) — free tier needs an API key, so it's the fallback,
  not primary. `source_pref = ["wikipedia", "fmp"]`.
- **PIT boundary:** **build-forward from today.** The Wikipedia Components table is a *current
  snapshot* with no dated leaves, so (per `refresh_universe`) the honest `pit_valid_from` is today —
  membership before inception is survivorship-biased and deliberately not back-projected. Same
  posture as the European flagships (dax/cac40/…). Documented, not a defect.
- **Monitor cadence:** the daily universe monitor (`sym universe monitor`) + sanity/corroboration
  gating (U3.2) and the membership-accuracy gate (U3.3). **Flag at first refresh:** the parse yielded
  **114** tokens vs the canonical **~101** Nasdaq-100 constituents — verify the Components table
  wasn't conflated with a changes/secondary table (multi-class names like GOOGL/GOOG inflate the
  count slightly; >110 warrants a look). The accuracy gate should catch a bad parse before it's
  trusted.
- **Gating:** `sym validate --universe nasdaq100` after population (completeness, referential
  integrity, price/calendar/lifecycle, returns-readiness).

## Operator population sequence (run after this plan is accepted)

1. `sym universe add nasdaq100 --kind index --name "Nasdaq 100" --index nasdaq100 --source-pref wikipedia,fmp`
2. `sym universe refresh nasdaq100`   # provider → append → OpenFIGI resolve → PIT projection
3. `sym universe members nasdaq100`   # verify count (~100-101) + resolution status
4. `sym load --scope universe:nasdaq100`   # EOD prices for the resolved members (yfinance)
5. fundamentals/market-cap backfill for the members (treemap sizing)
6. `sym universe-benchmark` / link `^NDX` (optional — analytics benchmark)
7. `sym validate --universe nasdaq100`

## Code change

- `packages/sym/src/sym/universe/providers/wikipedia.py` — added `nasdaq100` to `_BUILTIN_SPECS`
  (`{"title": "Nasdaq-100", "mic": "XNAS"}`; bare US tickers, no yahoo suffix). `fmp.py` already had it.

## Aside: SPCX (operator also asked "why is SPCX not in my universe")

`SPCX` is **not in the warehouse at all** — `GET /api/sym/securities?q=SPCX` and `?q=SPC` both return
**0 matches**. So it can't be in any universe: it was never ingested. `SPCX` was the *SPAC and New
Issue ETF* (delisted 2023) — an ETF, not an index constituent, so it would never enter the
index-membership universes we pull (S&P/FTSE/Nasdaq-100/…). If it's wanted, it would have to go in a
**custom-list** universe, and only if/when it's a live, resolvable security (it is delisted).
