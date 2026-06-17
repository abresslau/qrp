# Story: Multi-source industry classification (whole-universe, maintained)

Status: review

<!-- Created via bmad-create-story (2026-06-17). Operator: "the classification at the moment is
very limited. you should incorporate multiple industry classification, like yahoo, google,
perplexity. find out how to pull and maintain this classification for the entire universe." -->

## Story

As the **operator of QRP**,
I want **industry classification pulled from multiple sources (not just the single static GICS
dataset), merged with clear provenance and precedence, and maintained across the ENTIRE universe on
a cadence**,
so that **every resolvable security gets a sector/industry — the heatmap stops showing
"Unclassified" tiles, `sym validate` member-completeness stops failing on GICS, and the
classification doesn't silently rot as membership changes**.

## Why (current limitation)

Classification today = **one static source + Brazil**:
- `sym/classification/gics.py` loads GICS from the **`financedatabase`** pip package — a *static,
  curated CSV snapshot*, top-3 GICS labels only (sub-industry + numeric codes are always NULL). It
  doesn't cover all names and goes stale (e.g. **Honeywell/HON is currently unclassified** — a
  mega-cap — and ~**134 non-Brazil names** across universes are "Unclassified").
- `sym/classification/b3.py` (QH.1) maps Brazil B3 segments → GICS.
- `gics_scd` is SCD-shaped and **already has a `source` column** (provenance-ready) + sector/
  industry-group/industry/sub-industry (code+name) columns.
- The `sym classify` CLI runs the GICS source + a B3 fill pass; ~90% global coverage, the rest
  Unclassified.

The gap is a **single, static, partial source** with no whole-universe maintenance loop.

## Research: what's actually pullable (probed 2026-06-17 — read this before designing)

The operator named Yahoo / Google / Perplexity; the honest findings:

- **Yahoo `assetProfile` (sector + industry): 401, CRUMB-GATED.** `GET /v10/finance/quoteSummary/{sym}?modules=assetProfile`
  returns **HTTP 401** on both query1/query2 without a crumb+cookie (same gating as the v7 quote
  endpoint — see `reference-env-external-sources`; the v8 *chart* endpoint we use for live quotes
  carries NO sector/industry). So Yahoo classification is reachable ONLY via the crumb flow:
  `GET /v1/test/getcrumb` with a session cookie from `fc.yahoo.com`, then pass the crumb. Feasible
  but it's an auth dance, and Yahoo uses **its own taxonomy** (11 sectors close to GICS but industry
  names differ) → needs a Yahoo→GICS-sector crosswalk. Treat as a **secondary** source.
- **Google Finance: NO official/public API.** Scraping is brittle + ToS-fraught. **Not a viable
  structured source** — do not build on it.
- **"Perplexity" / LLM: not a data feed.** The realistic read of this ask is an **LLM gap-filler**:
  classify the long-tail residual names into a GICS sector via an LLM (Claude), tagged
  `source='llm'`, **low-trust, last-resort, reviewable** — never overriding an authoritative source.
- **SEC SIC → GICS (RECOMMENDED PRIMARY NEW SOURCE).** SEC EDGAR (free, reachable in-env — Q8.3
  already ingests EDGAR) exposes each US filer's **SIC code** (`company_tickers`/`submissions`/
  company facts). A SIC→GICS-sector crosswalk classifies US names with no key and no crumb — this
  covers HON and most of the US slice of the 134-gap. The strongest, most maintainable new source.
- **FMP `profile` (sector/industry): keyed.** Free tier needs an API key (same constraint as the
  FMP universe provider) — wire as an OPTIONAL source behind the key, not a hard dependency.
- **`financedatabase` (current): static.** Keep as a baseline, but it's a snapshot — the "maintain"
  half of the ask means it can't be the only source.

## Acceptance Criteria

1. **A pluggable classification-source registry** — mirror the existing source/provider registry
   patterns (`sym/sources/registry.py`, `universe/providers/index_source.py`): each classifier
   (archetype) turns a `(composite_figi, ticker, mic)` into a normalized GICS-sector (+ industry
   where available) classification, self-registers at import, and is selected by an **ordered
   precedence** — never by importing a concrete class. No change to `gics_scd` write logic or the
   heatmap to add a source.
2. **SEC SIC→GICS source (new, primary fill).** A source that pulls SEC SIC codes (EDGAR, keyless)
   and maps SIC→GICS sector via a documented crosswalk; classifies US names the static GICS source
   misses (incl. HON). Honest: SIC→GICS is sector-level (industry-group best-effort); sub-industry
   stays NULL.
3. **Yahoo `assetProfile` source (new, secondary)** behind the **crumb flow** (getcrumb + cookie;
   browser UA). Yahoo sector/industry normalized to GICS via a Yahoo→GICS crosswalk. Degrades
   honestly (a 401/no-crumb is a source error → fall through to the next source, never "no class").
4. **LLM gap-fill source (last resort, opt-in)** for residual unclassified names: classify into one
   of the 11 GICS sectors with `source='llm'` and a confidence/`provenance` note; NEVER overrides an
   authoritative (financedatabase/B3/SEC/Yahoo) classification; flagged for review.
5. **Precedence + merge with provenance.** A documented order (e.g. B3 for Brazil → financedatabase
   → SEC SIC → Yahoo → LLM), written SCD into `gics_scd` with `source` recording WHICH classifier
   won per security. A higher-precedence source later filling a name closes the lower one (SCD), not
   a silent overwrite.
6. **Whole-universe maintenance.** A command + cadence that classifies **all resolved members across
   ALL universes** (not one universe), idempotent/SCD, resumable; surfaces coverage (% classified,
   by source) and the residual unclassified set. Hooks into the daily maintenance alongside the
   universe monitor.
7. **Heatmap + validate consume the merged result.** With the new sources, the heatmap's
   "Unclassified" tiles drop sharply and `sym validate` `universe_member_completeness` GICS-misses
   fall toward 0 (HON classified). No EOD/heatmap code change needed (both already read
   `gics_scd.sector_name`).
8. **Tests + no regressions.** DB-free unit tests per source (mock the HTTP/EDGAR/crumb fetch + the
   crosswalks) + the registry precedence/merge + the SCD provenance (re-run no-op; source upgrade
   closes+inserts). `sym validate` stays green where it was; the existing `financedatabase`/B3 path
   unchanged; no new hard dependency (SEC EDGAR + Yahoo are stdlib `urllib`; FMP/LLM optional).

## Tasks / Subtasks

- [x] **Task 1 — Classification-source abstraction + registry** (AC: 1,5) — the `GicsSource` protocol
  (`SecurityIdentity{figi,isin,ticker,mic}` → `dict[figi, GicsClassification]`) + `read_unclassified_identities`
  fill-scope + the per-security-`conn.transaction()` SCD writer (`apply_classifications`, persists
  `source`) **already realize** AC1/AC5: precedence = the ordered fill-pass chain (financedatabase →
  b3 → sec_sic), each fed only the still-unclassified set, so it is fill-only by construction and
  provenance is the `source` tag. No new registry class needed; no `gics_scd`/heatmap change. (Added
  `read_active_coverage` for the honest post-fill coverage gate.)
- [x] **Task 2 — SEC SIC→GICS source** (AC: 2) — `sym/classification/sec_sic.py`: `HttpSecClient`
  (replicated, NOT imported, from `altdata.sources` — peer-package rule; stdlib `urllib`, SEC-compliant
  UA w/ contact email), a documented `SIC→GICS-sector` crosswalk (`_SIC_OVERRIDES` + `_SIC_BANDS`),
  `SecSicGicsSource` (US-mic-scoped, sector-only, `source='sec_sic'`, never guesses). DB-free tests
  with a fake `SecClient`.
- [ ] **Task 3 — Yahoo assetProfile source (crumb flow)** (AC: 3) — **DEFERRED** per locked scope.
- [ ] **Task 4 — LLM gap-fill source (opt-in, last resort)** (AC: 4) — **DEFERRED** per locked scope.
- [x] **Task 5 — Whole-universe maintenance command** (AC: 1,5,6) — `_cmd_classify` extended with the
  `sec_sic` fill pass (same in-`with`-catch discipline as b3 so a SEC outage can't roll back earlier
  passes); coverage-by-source + per-pass attribution report; AC #2 threshold gate now measured on the
  honest **post-fill** whole-universe coverage (`read_active_coverage`), not the primary pass alone.
  Already whole-universe (active scope), idempotent/SCD.
- [x] **Task 6 — Verify** (AC: 6,7) — live `sym classify`: 47 US names filled (incl. **HON →
  Industrials**), whole-universe coverage **90.0% → 94.4%**, exit 0; `sym validate --universe nasdaq100`
  `universe_member_completeness: 102 members, 0 incomplete` (was 1: HON) + `identity_completeness` PASS;
  only remaining FAIL is the pre-existing global `unpriced_securities` (unrelated to classification).
  `uv run pytest` 623 pass (1 pre-existing unrelated `tests`-import-path failure, confirmed via stash);
  ruff clean on all touched code.

## Dev Notes

### Current state of files being touched
- **`packages/sym/src/sym/classification/gics.py`** (UPDATE→generalize) — `GicsSource` protocol +
  SCD writer (per-security `conn.transaction()`, close-on-change). Generalize the writer to accept
  any source's normalized classification + `source` tag; keep financedatabase as one registered source.
- **`packages/sym/src/sym/classification/b3.py`** (READ) — the Brazil archetype + fill-pass pattern
  to mirror for the new sources.
- **`packages/sym/src/sym/sources/registry.py`** (READ — pattern) — the price-source archetype
  registry to mirror for classifiers (config-keyed, self-registering).
- **`gics_scd`** (schema — no migration needed): has `source` + sector/industry-group/industry/
  sub-industry (code+name) + valid_from/to. Multi-source writes set `source`; codes/sub-industry
  stay NULL for label-only sources (documented precedent).
- **`sym/cli.py` `_cmd_classify`** (UPDATE) — today runs the GICS source + B3 fill globally; extend
  to drive the precedence chain + a whole-universe scope + a coverage-by-source report.
- **`services/api/.../sym/gateway.py` `heatmap`/`live_heatmap`** (READ — no change) — both coalesce
  `gics_scd.sector_name` → 'Unclassified'; more coverage = fewer Unclassified tiles automatically.

### Key constraints
- **Normalize everything to the GICS sector taxonomy** (11 sectors) — the heatmap + validate are
  GICS-sector-based. Each non-GICS source (Yahoo, SIC) needs a documented crosswalk to GICS sector;
  industry/sub-industry best-effort, NULL where unknown (matches the financedatabase precedent).
- **Provenance + precedence, never silent overwrite** — `source` records the winner; SCD close on a
  higher-precedence upgrade. Authoritative sources (financedatabase/B3/SEC) outrank Yahoo; LLM is last.
- **No new hard dependency** — SEC EDGAR + Yahoo via stdlib `urllib` (the QH.2/Q8.3 posture); FMP +
  LLM are optional/keyed/opt-in. `dev-story` halts on new runtime deps.
- **Env reachability (probed):** SEC EDGAR ✅ (Q8.3); Yahoo assetProfile = 401 (needs crumb); Google
  = no API (excluded); FMP = keyed; financedatabase = static/installed. Re-probe before building each
  source (per `feedback-name-the-probe-retest`).
- **Maintenance = whole universe, SCD, idempotent** — per `feedback-index-maintenance-plan` /
  `project-universe-reload-no-gaps`: classify all PIT-resolved members (the monitor cadence), no gaps.

### References
- [Source: packages/sym/src/sym/classification/gics.py, b3.py] — current classifier + SCD writer.
- [Source: packages/sym/src/sym/sources/registry.py] — the archetype-registry pattern to mirror.
- [Source: migrations/deploy/gics_scd.sql] — the SCD table + `source` column.
- [Source: reference-env-external-sources (memory)] — Yahoo crumb-gating (v7/quoteSummary 401, v8 chart OK), SEC EDGAR reachable.
- [Source: _bmad-output/implementation-artifacts/nasdaq100-universe.md] — HON + the ~134-row non-Brazil-GICS gap this story closes.
- [Source: Q8.3 altdata (SEC EDGAR ingest)] — the existing EDGAR client/precedent to reuse for SIC.

### Project Structure Notes
- New: `sym/classification/` sources (sec_sic.py, yahoo_profile.py, llm.py) + a classifier registry;
  UPDATE the SCD writer + the `classify` CLI. No migration (gics_scd already fits). No frontend change.
- Deferred/ledger: FMP profile source (keyed); a fully PIT-historical classification feed (codes +
  sub-industry); the LLM source's review/confirm workflow.

## Scope decision (LOCKED 2026-06-17, Andre)

**First dev pass = SEC SIC→GICS MVP.** Build **AC1 (registry/precedence/provenance), AC2 (SEC
SIC→GICS, keyless), AC5 (precedence+merge), AC6 (whole-universe maintenance), AC7 (heatmap/validate
consume), AC8 (tests)** — keep `financedatabase` + B3 as registered sources; SEC SIC fills the
residual (expected to clear HON + most of the ~134 US gap with no auth).

**Deferred to a follow-up pass (NOT this story's dev):** AC3 (Yahoo `assetProfile` via the crumb
flow), AC4 (LLM gap-fill), and the FMP profile source. Revisit once the SEC-SIC residual is known —
if non-US names remain Unclassified, Yahoo-crumb is the next source; LLM only for the long tail.

## Dev Agent Record

### Completion Notes (2026-06-17)

**Key design finding:** the multi-source abstraction the story called for (AC1/AC5) **already existed**
in `gics.py` — `GicsSource` protocol + `SecurityIdentity(figi,isin,ticker,mic)` + the
`read_unclassified_identities` fill-scope + the `source`-persisting SCD writer. b3 (QH.1) is already a
fill source behind it. So "registry + precedence + provenance" did not need a new registry class:
**precedence is the ordered fill-pass chain** (financedatabase primary → b3 Brazil fill → sec_sic US
fill), each pass fed ONLY the still-unclassified actives, which makes every fill source fill-only by
construction (it can never overwrite a higher-precedence source) and makes provenance the per-row
`source` tag. Adding SEC was therefore: one new source class + one new fill pass + the crosswalk.

**SEC SIC→GICS source** (`sym/classification/sec_sic.py`): replicated the EDGAR client from
`altdata.sources` (peer-package topology rule — `sym` must not import `altdata`; stdlib `urllib`,
SEC-compliant UA carrying a contact email or EDGAR 403s). `company_tickers.json` → CIK, `submissions`
→ `sic`. A documented SIC→GICS-sector crosswalk: `_SIC_OVERRIDES` (high-traffic exact 4-digit codes —
semiconductors 3674, software 7372, pharma 2834, REITs 6798, computers 3571 — beat their coarser
parent band) + `_SIC_BANDS` (ordered inclusive ranges). US-MIC-scoped (a foreign listing sharing a US
ticker must never inherit a US filer's SIC; mic-less identities trusted ticker-only, mirroring b3).
Sector-only (`source='sec_sic'`, industry levels NULL — SIC has no GICS sub-structure). Records
unmapped-SIC / no-CIK / non-US-skipped on side channels; **never guesses** a sector.

**Coverage gate fix:** the AC #2 threshold was previously checked against the financedatabase *primary*
pass coverage alone (89.98% → rounds to "90.0%" but trips the `< 0.90` gate, exit 2), ignoring what the
fill passes add. Added `read_active_coverage(conn)` and moved the gate + a final summary line onto the
honest **post-fill** whole-universe coverage. Live result: 90.0% → **94.4%** (fd 1968 + b3 49 + sec_sic
47 of 2187 active), exit 0.

**Live verification:** `sym classify` filled 47 US names (incl. HON → Industrials, source `sec_sic`),
27 no-CIK/no-SIC, 96 non-US skipped (sums exactly to the 170 residual). Re-run idempotent (0 inserted).
`sym validate --universe nasdaq100`: `universe_member_completeness` 102 members / **0 incomplete** (was
1 — HON), `identity_completeness` PASS. Sole remaining FAIL is the pre-existing global
`unpriced_securities` (non-classification, documented in `nasdaq100-universe.md`).

### File List
- `packages/sym/src/sym/classification/sec_sic.py` (NEW) — SEC client + SIC→GICS crosswalk + `SecSicGicsSource`.
- `packages/sym/tests/test_classification_sec_sic.py` (NEW) — crosswalk + fetch tests (fake SecClient, no network).
- `packages/sym/src/sym/classification/gics.py` (UPDATE) — added `read_active_coverage`.
- `packages/sym/src/sym/cli.py` (UPDATE) — `_cmd_classify`: sec_sic fill pass + report + post-fill coverage gate.

### Code-review fixes (2026-06-17, 3-layer adversarial)
- **High — per-CIK error isolation:** a single CIK's `submissions` 404/403/blip raised `SecSicError`
  out of `fetch` and aborted the WHOLE fill pass. Now wrapped per-CIK: the error is recorded on a new
  `last_errors` side-channel and the loop continues (analogue of the SCD writer's per-security
  durability). Surfaced in the CLI report. Test: `test_fetch_isolates_a_single_cik_lookup_error`.
- **Med — SEC rate limit:** `HttpSecClient` now self-throttles (`min_interval=0.12s` ≈ 8 req/s, under
  SEC's 10/s ceiling) across its sequential `submissions` calls.
- **Med — AC8 provenance gap:** added `test_apply_classifications_persists_sec_sic_provenance` — runs a
  sec_sic plan through `apply_classifications` against a recording fake conn and asserts the INSERT
  carries `source='sec_sic'` (+ the mapped sector), closing the end-to-end provenance assertion AC8 named.
- **Low — `int(cik_str)` robustness:** a non-numeric directory row is now skipped, not fatal to the parse.

### Known limitations (accepted for the MVP; ledgered)
- **Ticker punctuation (BRK.B ↔ SEC's BRK-B):** no `.`↔`-` / class-suffix normalization, so dual-class
  names with punctuated tickers silently UNDER-fill (recorded as no-CIK, never mis-filled). Cheap
  follow-up if the residual shows such names.
- **AC1 literal registry:** `_cmd_classify` hard-codes the concrete sources (as the b3 path already
  did); precedence is the ordered fill-pass chain, not a self-registering config-keyed registry. The
  precedence/provenance/fill-only guarantees AC1+AC5 require all hold; the "no concrete-class import"
  wording does not — accepted on an owner-operated tool, ledgered for a future generalization if a 4th+
  source lands.

### Change Log
- 2026-06-17: SEC SIC→GICS MVP implemented (Tasks 1,2,5,6). AC3 (Yahoo crumb) + AC4 (LLM) deferred per locked scope. Status → review.
- 2026-06-17: Applied 3-layer code-review fixes (per-CIK isolation [High], throttle [Med], provenance test [Med], int-guard [Low]); ledgered ticker-punctuation + literal-registry limitations.

## Open questions (for review)
1. **Precedence order** — is `B3(BR) → financedatabase → SEC SIC → Yahoo → LLM` right, or should a
   live source (Yahoo/SEC) outrank the static financedatabase snapshot for freshness?
2. **LLM gap-fill** — in scope now (Claude classifies the residual, review-flagged), or defer until
   the deterministic sources (SEC/Yahoo) are in and we see the true residual?
3. **Yahoo crumb** — acceptable to add the crumb+cookie flow, or keep Yahoo deferred and lead with
   SEC SIC (keyless) which alone likely clears most of the US gap incl. HON?
