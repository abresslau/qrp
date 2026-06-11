# Story QH.1: Close the Brazil GICS gap — B3 sector classification source

Status: done

## Story

As Andre (the operator),
I want the unclassified Brazilian names classified from B3's own published sector taxonomy (mapped explicitly to GICS sectors),
so that the IBOV/IBX heatmap stops showing half the index as "Unclassified" and the `universe_member_completeness` validate FAILs for Brazil clear.

## Background + scope decision

Epic QH Story QH.1 `[NEW]` (epics-qrp-roadmap.md): *"the 43/78 IBOV (and other) names left `Unclassified` get GICS sectors from a source beyond the financedatabase free tier; the heatmap 'unclassified' group shrinks; the `universe_member_completeness` validate FAIL clears."*

**Live baseline (queried 2026-06-11):** 226 FAIL rows missing `gics` across universes — **ibov 43, ibx 49** (the Brazil scope), ftse100 69, sp600 18, ftsemib 11, others smaller. BVMF actives: 49/99 unclassified. The BVMF names carry **no ISINs** in `security_symbology` — which is exactly why Story 1.8's financedatabase ISIN fallback never lifted them.

**Env probe 2026-06-11 (real payloads):**

| Source | Status | Use |
|---|---|---|
| B3 `GetPortfolioDay` **segment=2** ("setor de atuação" view) | ✅ 200 UTF-8 JSON: IBOV 78 rows, IBXX 99 rows, every row carries `segment` = "Setor / Subsetor" + `cod` = ticker | IN — the authoritative exchange classification for exactly our BVMF universe |
| SEC submissions `sic`/`sicDescription` (Q8.3 lead) | ✅ verified in Q8.3 | OUT — not needed for Brazil (B3 is direct + authoritative); keep as the candidate for ADR-bearing non-Brazil gaps. SIC→GICS is a big messy mapping; B3→GICS is 11-ish sectors |
| financedatabase | already in use (Story 1.8) | unchanged — stays the primary source |

**Console-print caveat from the probe:** the B3 payload is clean UTF-8 (`charset=utf-8`, accents verified in-process); mojibake seen in terminal output is Windows console cp1252 rendering, NOT the data. Do not "fix" encoding.

**The design decision — explicit B3→GICS sector mapping.** B3's sector taxonomy ("Bens Industriais", "Consumo Cíclico", "Petróleo, Gás e Biocombustíveis", …) parallels the 11 GICS sectors closely but IS NOT GICS. The honest move: a small, reviewable, **hardcoded mapping table** from B3 sector (the part of `segment` before "/") to GICS sector NAME, with `gics_scd.source = 'b3'` recording provenance, **sector level only** — industry-group/industry/sub-industry stay NULL (same depth-honesty precedent as 1.8's "labels to the depth the source provides"). An unmapped segment value is attributed and skipped, never guessed.

**Mapping subtleties found in the live data (build the table from OBSERVED values, then verify live):**
- The `segment` strings are ABBREVIATED and inconsistent ("Bens Indls / Máqs e Equips", "Cons N Cíclico / Bebidas", "Cons N  Básico / Alimentos Processados" — note double space, and "Ciclico" without accent appears too). Normalise (collapse whitespace, casefold for matching) and key the map on normalised prefixes.
- "Financ e Outros / Explor Imóveis" → **Real Estate** (subsector-level exception); all other "Financ e Outros" → Financials. Map on the full normalised string for the exception, prefix for the rest.
- A bare "Diversos" appears as a standalone segment — inspect which ticker carries it during dev; if genuinely ambiguous leave it UNMAPPED (attributed residual), do not guess.

**Explicitly OUT of scope:** ftse100/US/other-market GICS gaps (different sources — ledger with the SEC SIC lead); the B3 `CompanyCall` per-company endpoints (portfolio segment=2 already covers our exact universe); GICS codes / sub-sector depth; any console change (the heatmap reads `gics_scd.sector_name` live — it updates by itself); point-in-time classification history beyond the existing SCD shape.

## Acceptance Criteria

1. **`B3GicsSource` implements the existing `GicsSource` Protocol** (`packages/sym/src/sym/classification/`): fetches IBOV + IBXX portfolios via the segment=2 view (reusing the B3 token/request conventions from `universe/providers/b3.py` — `requests`, retries, loud `IndexSourceError`-style failure, pageSize=500 single-page guard), unions the rows, maps `cod` (ticker) → our `composite_figi` and `segment` → GICS sector through the explicit mapping table. Pure parsing/mapping separated from I/O (house pattern); client injectable for tests.
2. **Mapping is explicit and honest:** hardcoded normalised B3→GICS table; "Financ e Outros / Explor Imóveis" → Real Estate; unmapped segment values are counted + reported per ticker (never guessed, never written); the mapping is documented in the module docstring as a deliberate cross-taxonomy approximation with `source='b3'` provenance.
3. **Fill-only precedence:** B3 classifies ONLY securities with no currently-effective `gics_scd` row — financedatabase (3 levels) always wins over B3 (1 level); a B3 pass never closes/overwrites an existing classification. Idempotent re-run = no-op (the existing `apply_classifications` unchanged-row guard).
4. **Ticker→figi resolution via sym's own symbology** (current `security_symbology` ticker rows, BVMF scope) — reuse/mirror `read_active_identities`; unresolved B3 tickers attributed in the summary, not fabricated.
5. **`sym classify` runs both sources:** financedatabase pass (unchanged behavior + coverage gate), then the B3 fill pass over remaining unclassified actives; summary reports each pass distinctly. No new CLI command; flags only if genuinely needed.
6. **Tests** (house style, no network, extend `tests/test_classification.py` or a new `test_classification_b3.py`): segment-string normalisation + mapping (incl. the Real-Estate exception, the double-space/accent variants, unmapped→skipped+counted); fill-only behavior (a fake conn with an existing classification is untouched); ticker→figi resolution incl. unresolved attribution; parse of a fixture `results` payload; B3 source returns only sector level (other levels None, `source='b3'`).
7. **Live verification:** `sym classify` run → BVMF unclassified count drops from 49 to ~0 (any residual is named + explained, e.g. an unmapped "Diversos"); `sym validate` (or the completeness check directly) re-evaluated → ibov/ibx `missing gics` FAILs drop 43/49 → ~0; the heatmap API for ibov shows the Unclassified group shrunk accordingly; epic QH.1 → `[BUILT 2026-06-11]`; ledger updated (ftse100/US gaps + SEC SIC fallback lead recorded as the remaining-classification-gap item).

## Tasks / Subtasks

- [x] Task 1: `classification/b3.py` — segment parsing, normalisation, B3→GICS mapping table, `B3GicsSource` (AC: 1, 2, 4) — normalisation = NFD-strip-accents + casefold + collapse-whitespace (covers "Cíclico/Ciclico" + double-space variants with one key each); full-string exception map checked before the sector-prefix map; `HttpB3SectorClient` mirrors the universe provider's conventions (retries, loud non-200/non-JSON/no-results, totalPages>1 guard); zero-constituent union raises `B3ClassificationError`
- [x] Task 2: Fill-only orchestration — `read_unclassified_identities` added to `gics.py` (active + NOT EXISTS currently-effective gics row — the fill-only guarantee lives in the SQL); `_cmd_classify` runs the B3 pass after financedatabase, prints a distinct per-pass summary incl. per-ticker unmapped segments, and a B3 failure is reported without masking the primary pass (exit gate stays fd-coverage-based per Constraint 3)
- [x] Task 3: Tests (AC: 6) — `tests/test_classification_b3.py`: 30 live-observed segments parametrized against expected GICS sectors (the 31st, Explor Imóveis, covered by the exception tests); Real-Estate exception incl. slash-spacing/spelling variants; unknown segment → None never guessed; parse skips cod/segment-less rows; source emits sector-only + `source='b3'`; unmapped recorded + reset between fetches + recorded for out-of-request constituents (drift); mic scoping (foreign ticker collision never classified); cross-view conflict skipped not last-wins; in-scope-unfilled attribution; empty portfolios raise; ticker-less identities ignored; fill-only SQL asserted via recording conn. **47 tests green** (18 functions; post-review count)
- [x] Task 4: Live run + verification + finishers (AC: 7)
  - [x] `sym classify`: fd pass 1935/2146 (90.2%, all unchanged) + **B3 fill pass: 211 unclassified active → 49 inserted, 0 unmapped, 0 failed**
  - [x] `sym validate` re-run: ibov/ibx `missing gics` FAILs **43+49 → 0** (completeness FAIL rows 226 → 148, all remaining non-Brazil); `gics_scd` now 1935 financedatabase + 49 b3; sector distribution sane (11 Utilities, 10 Materials, 7 Energy, …, 2 Real Estate)
  - [x] ibov heatmap live: **Unclassified group GONE** — 72/72 shown cells sectored
  - [x] Epic QH.1 → `[BUILT 2026-06-11]` (+ build-status bullets); ledger: non-Brazil gaps (134 rows, SEC-SIC/LSE leads), index-portfolio scope caveat, abbreviation-drift watch item

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] Fill-pass exception escape destroys the PRIMARY pass: `connect()` is non-autocommit, so the fd pass's per-figi `conn.transaction()` are savepoints in one outer transaction — any exception escaping the narrow `(B3ClassificationError, OSError)` catch (psycopg errors, AttributeError from a B3 shape break, anything from `read_unclassified_identities` which sits OUTSIDE the try) exits the `with connect()` abnormally and rolls back every fd write. Catch `Exception` around the whole fill section incl. the read [cli.py _cmd_classify] (HIGH, blind+edge)
- [x] [Review][Patch] Real-Estate exception defeated by slash-spacing/spelling variants — the feed mixes "X / Y" and "X/Y" plus "Financ e Outros"/"Financeiro e Outros"; a property row arriving in an uncovered form silently maps to Financials via the prefix rule (wrong write, not an unmapped report). Canonicalise slashes in `normalise_segment` + cover both sector spellings in the full-string map [b3.py] (HIGH, blind+edge)
- [x] [Review][Patch] Ticker-only matching over the GLOBAL unclassified pool — a non-Brazil unclassified name sharing a ticker string with a B3 constituent gets a Brazilian sector written to the wrong figi. Add `mic` to `SecurityIdentity` + both read queries; B3 source matches mic-carrying identities only when BVMF [b3.py, gics.py] (MED, blind+edge)
- [x] [Review][Patch] Drift detection blind for already-classified names: `if identity is None: continue` runs before mapping, so a new B3 abbreviation on an fd-classified constituent never reaches `last_unmapped` — the deferred-work "surfaces loudly" claim only held for unclassified names. Map before identity-match [b3.py fetch] (MED, blind)
- [x] [Review][Patch] IBOV/IBXX disagreement is silent last-wins: `update()` lets one view override the other; if the two views map to DIFFERENT GICS sectors, skip + report (never guess), classify only when they agree [b3.py fetch] (LOW, edge)
- [x] [Review][Patch] AC4 attribution missing: fill-scope identities B3 could not classify are only inferable from count arithmetic; track `last_unmatched` on the source + print per-ticker; also surface `b3_summary.failures` (collected but dropped) and `rows_closed` (the invariant violation detector) in the CLI output [b3.py, cli.py] (MED, auditor+blind)
- [x] [Review][Patch] No-op fill still hits B3 live: with zero unclassified identities the command pays two network round-trips and can print FAILED for a no-op; skip the pass when there is nothing to fill [cli.py] (LOW, blind+edge)
- [x] [Review][Patch] "N unmapped segments" counts tickers, not segments — relabel honestly [cli.py] (LOW, blind)
- [x] [Review][Patch] Story File List test-count wrong (claimed 13 tests/42 cases; actual 11/40, parametrize list is 30 with the 31st segment covered by the exception test) — correct the record [story file] (LOW, auditor)
- [x] [Review][Patch] AC6 gaps: no slash-variant tests, no mic-scoping tests, no unmatched-attribution test, no conflict test — add with the behavior patches [tests] (MED, auditor)
- [x] [Review][Defer] `max(symbol_value)` picks an alphabetically-arbitrary current ticker per figi — pre-existing Story-1.8 pattern in `read_active_identities`, shared by the new query; needs a listing-preference design if multi-listed names ever appear — deferred, ledgered
- [x] [Review][Defer] Exit code never reflects a failed/partial fill pass (fd-gate-only is Constraint 3 by design; automation distinguishing fill outage from success needs a deliberate exit-code design) — deferred, ledgered

Dismissed as noise (3): non-200 not retried + final-attempt sleep dead time (faithful mirrors of the proven `HttpB3Client` conventions — divergence would be the bug); `totalPages` non-int bypass (inherited verbatim from the proven provider, same exposure there — single ledger item would belong to the provider, not this mirror); duplicate tickers WITHIN one exchange's current symbology (no live instance; the cross-exchange case is the mic patch).

## Dev Notes

### Verified source contract (probed 2026-06-11 — build to THIS)

- URL: `https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{base64-token}`; token = b64 of `{"language":"pt-br","pageNumber":1,"pageSize":500,"index":"IBOV","segment":"2"}` — **`segment:"2"` is the sector view** (the existing membership provider uses `"1"`).
- Row shape (segment=2): `{"segment":"Bens Indls / Máqs e Equips","cod":"WEGE3","asset":"WEG","part":"2,692",...}`. UTF-8. `page.totalPages` present (guard >1 like the membership client).
- IBOV→78 rows, IBXX→99 rows; the union covers the current 99 BVMF actives (they were seeded from these two indexes).

### Existing code map (READ before writing)

- `packages/sym/src/sym/classification/gics.py` — the whole machinery to reuse: `GicsSource` Protocol, `GicsClassification` (set only `sector_name`, `source="b3"`), `plan_classifications`, `apply_classifications` (SCD-safe, same-day in-place, per-security error isolation), `read_active_identities`, `ClassificationSummary`.
- `packages/sym/src/sym/universe/providers/b3.py` — B3 request conventions to mirror (token builder, retries, totalPages guard, loud empty-parse error). Do NOT couple to it (it's the universe domain); copy the small token helper or import if clean.
- `packages/sym/src/sym/cli.py` `_cmd_classify` — where the second pass wires in.
- `packages/sym/src/sym/validate/completeness.py` — `has_gics` = currently-effective `gics_scd` row exists; nothing to change here.
- `services/api/src/qrp_api/modules/sym/gateway.py` `heatmap()` — `coalesce(g.sector_name,'Unclassified')`; updates by itself.

### Constraints

1. GICS sector NAMES must be the canonical 11 GICS sector labels (Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, Health Care, Financials, Information Technology, Communication Services, Utilities, Real Estate) — the heatmap groups by exact string.
2. SCD discipline unchanged: writes go through `apply_classifications` ONLY (never raw SQL inserts); `as_of_date` param naming canonical.
3. Coverage gate: `sym classify`'s exit-code gate stays financedatabase-pass semantics (don't let the B3 pass mask an fd regression); overall coverage will rise as a side effect.
4. sym tests: 543/544 baseline (test_durable_reviews import failure is pre-existing/ledgered — don't chase).
5. Ruff line-length 100; tests DB-free with fake conns/clients (house style).
6. No new deps — `requests` is already a sym dependency (universe providers use it).

### Previous story intelligence (Q8.3/Q8.4 review themes — pre-empt)

- Counters must count what they claim (per-pass summaries: classified/unmapped/unresolved distinct).
- Per-item failure attribution (a bad ticker doesn't kill the run; reasons named).
- Shape-break honesty: missing `results`/`segment` keys → loud error, not ok:0 (Q8.3 review finding pattern).
- Honest docstrings: the mapping is an approximation; say so where it lives.
- Mojibake is console rendering; data is UTF-8 — don't add encoding hacks.

### References

- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md — Epic QH, Story QH.1]
- [Source: _bmad-output/implementation-artifacts/1-8-gics-classification.md — the classification machinery + depth-honesty precedent]
- [Source: packages/sym/src/sym/classification/gics.py; universe/providers/b3.py; validate/completeness.py]
- [Source: live probes + DB baseline this session, 2026-06-11]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Mojibake confirmation: B3 payload is `charset=utf-8` and decodes clean in-process; terminal � is cp1252 console rendering — no encoding hacks added (story caveat held).
- "Diversos" resolution: carriers are COGN3/RENT3/VAMO3/YDUQ3/ANIM3/MOVI3 (education + car/truck rental) — B3's taxonomy places the *Diversos* subsector under *Consumo Cíclico*, so → Consumer Discretionary on B3's own authority (documented in the module docstring), not a guess.
- Ruff: 7 findings in `cli.py` are pre-existing on clean HEAD (verified by stash-and-rerun); my regions lint clean.

### Completion Notes List

- **All 7 ACs met.** The B3 source rides the existing Story-1.8 machinery end-to-end: `GicsSource` Protocol implementation + `plan_classifications` + `apply_classifications` (SCD discipline untouched, zero new write paths).
- **Fill-only by construction, not by check:** the B3 pass is fed only `read_unclassified_identities` output, so it cannot close/overwrite a financedatabase row — precedence is structural.
- **Every observed segment mapped (31/31)** and the mapping is provenance-honest: `source='b3'`, sector level only, the cross-taxonomy approximation stated where it lives.
- **Live outcome:** BVMF unclassified 49 → 0; ibov/ibx missing-gics FAILs 43+49 → 0; ibov heatmap Unclassified group eliminated (72/72 sectored). Residual 134 gics FAILs are non-Brazil — explicitly out of scope, ledgered with source leads.
- Suites: sym 590 passed + the 1 ledgered pre-existing failure (`test_durable_reviews` import, invocation-specific); 47/47 b3 + 13/13 1.8 classification tests. Ruff finding count identical to clean HEAD (17, all pre-existing).
- **Post-review re-run (live):** fd pass unchanged (1935 unchanged); fill pass now reports "162 unclassified active; 0 inserted … 0 in-scope unfilled" — the 162 are all non-BVMF, mic-scoped out of B3's reach; the 49 b3 rows stand untouched (idempotency + fill-only proven live again after the patches).

### File List

- packages/sym/src/sym/classification/b3.py (new — normalisation incl. slash canonicalisation, B3→GICS mapping with both Real-Estate spellings, parse, HttpB3SectorClient, B3GicsSource with mic scoping + unmapped/conflict/unmatched attribution)
- packages/sym/src/sym/classification/gics.py (modified — `SecurityIdentity.mic`; `read_unclassified_identities` fill-scope query carrying mic)
- packages/sym/src/sym/cli.py (modified — `_cmd_classify` B3 fill pass: whole pass inside one catch (primary-pass rollback hazard), skip-when-nothing-to-fill, honest per-pass summary incl. closed/conflicts/unfilled/failures)
- packages/sym/tests/test_classification_b3.py (new — 18 tests / 47 cases)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — QH.1 `[BUILT 2026-06-11]` + build-status bullets)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — QH.1 section: non-Brazil gaps, scope caveat, drift watch + review deferrals)

## Change Log

- 2026-06-11: Story created (probe-first: B3 segment=2 sector view verified live for IBOV+IBXX; explicit B3→GICS sector mapping scoped; SEC SIC lead parked for non-Brazil gaps).
- 2026-06-11: Implemented — `B3GicsSource` (sector-only, `source='b3'`, explicit normalised mapping incl. Real-Estate exception + Diversos placement), fill-only pass in `sym classify`, 13 tests. Live: 49/49 BVMF classified, 0 unmapped; ibov/ibx gics FAILs → 0; ibov heatmap fully sectored. Status → review.
- 2026-06-11: Code review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) — 10 patches applied (headline: the fill pass's exception escape would have ROLLED BACK the whole financedatabase pass — non-autocommit connection makes per-figi transactions savepoints; whole pass now inside one catch. Also: slash-spacing variants no longer defeat the Real-Estate exception; mic scoping kills cross-exchange ticker collisions; drift surfaces for already-classified names; cross-view conflicts skip instead of last-wins; AC4 unfilled attribution + failures surfaced; no-op runs skip B3; honest counter labels; record corrections; +7 tests → 47), 2 deferred (arbitrary `max(ticker)` pick — pre-existing 1.8 pattern; fill-failure exit-code design), 3 dismissed (faithful-mirror conventions). Live re-run: idempotent, 49 b3 rows stand, 162 non-BVMF correctly out of scope. sym 590+1 ledgered. Status → done.
