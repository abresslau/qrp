# Story: Multi-source classification matrix — every source's opinion per company (+ Wikidata, Perplexity, Google)

Status: done

<!-- Created via bmad-create-story (2026-06-18). Operator: "we need to have multiple classification
for same company ... you need to pull from Google and Perplexity." Decisions captured 2026-06-18:
run ALL sources over ALL companies; include FMP + LLM; add Google + Perplexity. NOT in an epic
decomposition — standalone classification-track artifact (like classification-multisource). -->

## Story

As the **operator of QRP**,
I want **every classification source to record its OWN GICS opinion for every company — not just the
single precedence-winner — stored independently, including two new web-grounded LLM sources
(Perplexity and Google), so each company carries the full set of "what each source says"**,
so that **I can compare sources, see disagreement, and trust the merged classification — while the
precedence-resolved `gics_scd` stays the single source of truth the heatmap and `validate` consume**.

## Why (current limitation — only ONE opinion per company exists)

Classification today is a **fill-only precedence chain**: the highest-precedence source that covers a
company classifies it, and lower sources only ever see the **residual** (`read_classifiable_identities`
returns unclassified + strictly-lower-held names). Consequences:

- A company classified by `financedatabase` is **never even shown** to `yahoo_profile` / `sec_sic` /
  `fmp` — so their opinion of it is never recorded. Only the winner's opinion exists.
- The detail view's "Classification by source" table (shipped in `explorer-enrichment`) reads
  `gics_scd`, which holds **one effective row per figi** (enforced by the `gics_scd_no_overlap`
  exclusion constraint). So for almost every company it shows a single row — not "multiple
  classifications."

There is, by design, **no place that holds source B's opinion of a company source A already
classified.** This story adds that, without disturbing the resolved classification everything
downstream depends on.

## Reachability (probed 2026-06-18 — read before building; name-the-probe rule)

| Source | Endpoint | Probe result | In this story |
|--------|----------|--------------|---------------|
| financedatabase | (pip package) | installed | run over ALL names |
| b3 | B3 segment view | in-DB | run over ALL names |
| sec_sic | SEC EDGAR | keyless, reachable | run over ALL names |
| yahoo_profile | Yahoo crumb flow | keyless, reachable | run over ALL names (slow — see cost note) |
| fmp | FMP `/profile` | keyed | dormant (no `FMP_API_KEY` in-env) — built + unit-tested, not live-verified |
| llm | Claude artifact (`llm_classifications.json`) | in-repo, no runtime API | opinion = the reviewed artifact |
| **wikidata** (NEW) | `query.wikidata.org/sparql` (`industry` P452) | **200 OK — keyless, reachable** | run over ALL names — **live in-env**, real structured signal |
| **perplexity** (NEW) | `api.perplexity.ai/chat/completions` (Sonar) | **HTTP 401 — reachable, keyed** | built + unit-tested, **dormant** (no `PERPLEXITY_API_KEY`) |
| **google** (NEW) | `generativelanguage.googleapis.com` (Gemini) | **HTTP 403 — reachable, keyed** | built + unit-tested, **dormant** (no `GOOGLE_API_KEY`) |

**Why Wikidata, not scraping Google/Perplexity (decided 2026-06-18):** Google/Perplexity are LLM answer
engines, not structured feeds — scraping them is brittle, ToS-violating, bot-blocked, AND redundant
(an LLM's guess = exactly what the `llm` source already gives). **Wikidata** (probed: Apple → software /
electronics / consumer-electronics / IT industry) is a free, keyless, *structured* `industry (P452)`
source that adds genuinely new signal, live in-env. So Wikidata is built to run now; Perplexity/Google
remain keyed-dormant for the future (no scrapers).

**Honest framing of "Google" and "Perplexity":** neither publishes a structured *GICS sector* feed.
What they offer is an **answer engine / LLM** you call with a question. So both are added as
**web-grounded LLM classifiers** (ask "what GICS sector is `<company, ticker, MIC>`?", map the answer
to one of the 11 GICS sectors) — the same archetype as the existing `llm` source, just via the
Perplexity Sonar and Google Gemini APIs. **Google Finance scraping remains rejected** (no API, brittle,
ToS — see `classification-multisource.md`). Both new sources are **low-trust** (LLM tier) and **keyed**
— in-env they are dormant (no keys), so they ship production-ready + unit-tested against a fake client
(the FMP precedent), not live-verified here.

## Scope decision (documented)

- **`gics_scd` is UNCHANGED.** It remains the precedence-resolved, one-effective-row-per-figi truth
  the heatmap, `validate`, and the explorer's effective classification read. This story does not touch
  the fill chain or `apply_classifications`.
- **New independent store `gics_source_opinion`** holds every source's own classification per company,
  SCD-shaped, with the no-overlap exclusion keyed on **(composite_figi, source)** so multiple sources
  coexist for one company.
- **New opinion pass** runs ALL sources over ALL active identities (`read_active_identities`), writing
  each source's opinion into the store (SCD close+insert on change; re-run is a no-op).
- **The detail "Classification by source" reads the opinion store** → genuinely multi-row, with the
  precedence-effective source flagged (cross-referenced to `gics_scd`).

**Cost / cadence (documented):** running `yahoo_profile` over all ~2,180 names is slow (~1.2s/name
crumb fetch ≈ tens of minutes) — and the keyed LLM sources cost per call. So the opinion refresh is an
**explicit, on-demand pass** (`sym classify-opinions`, or `sym classify --opinions`), **NOT** part of
the nightly EOD. The `yahoo_profile` circuit-breaker (from `classification-robustness`) and per-symbol
isolation already protect it; the new LLM sources reuse the same guards.

## Acceptance Criteria

1. **New `gics_source_opinion` store.** A migration adds a table mirroring `gics_scd`'s GICS-level
   columns + `source` + `valid_from`/`valid_to`, with a `(composite_figi, source)` no-overlap
   exclusion (so each source has at most one effective row per company, but sources coexist), the
   securities FK, and indexes on `composite_figi`, `source`, `sector_name`. Sqitch deploy/revert/verify
   + plan entry, idempotent. **No change to `gics_scd`.**
2. **Every source runs over every company.** A new pass feeds **all active identities**
   (`read_active_identities`) to **each** source's `fetch(...)` (not the residual) and writes each
   returned opinion into `gics_source_opinion` via an SCD writer (close+insert when a source's opinion
   for a company changes; in-place no-op when unchanged; re-run idempotent). Keyless sources
   (financedatabase, b3, sec_sic, yahoo_profile) run live; keyed/opt-in sources (fmp, perplexity,
   google, llm) run only when their key/flag is present, emitting a clean "skipped — no <KEY>" line
   otherwise (the FMP precedent).
3. **Wikidata source (NEW, keyless, structured — LIVE).** `sym/classification/wikidata.py` —
   `WikidataGicsSource` over the `query.wikidata.org/sparql` endpoint (no key, stdlib `urllib`, batched
   SPARQL by `isin`/ticker→Wikidata QID). Reads `industry (P452)` claims and maps them to a GICS sector
   via a documented **Wikidata-industry → GICS crosswalk** (the analogue of the SIC→GICS / Yahoo→GICS
   crosswalks; a company has several industry claims — pick the dominant mapped sector deterministically,
   record unmapped without guessing). `source='wikidata'`, sector-only. Per-entity isolation +
   circuit-breaker. This source RUNS in-env and contributes real signal.
4. **Perplexity source (NEW, keyed, LLM tier — dormant).** `sym/classification/perplexity.py` —
   `PerplexityGicsSource` over the Sonar `chat/completions` API (gated on `PERPLEXITY_API_KEY`; stdlib
   `urllib`). Prompts for a single GICS sector per `(name, ticker, mic)`, validates the answer ∈ the 11
   GICS sectors (off-taxonomy → unmapped, never guessed), `source='perplexity'`, sector-only, per-symbol
   isolation + circuit-breaker. Dormant in-env (no key) — built + unit-tested, not live-verified.
5. **Google source (NEW, keyed, LLM tier — dormant).** `sym/classification/google_gemini.py` —
   `GoogleGeminiGicsSource` over the Gemini `generateContent` API (gated on `GOOGLE_API_KEY` /
   `GEMINI_API_KEY`), same archetype/guards as AC4, `source='google'`. Documented: this is Google's
   **LLM** (Gemini), not a structured feed; Google-Finance/UI scraping is explicitly out of scope.
   Dormant in-env (no key) — built + unit-tested, not live-verified.
6. **Precedence + registry updated.** `SOURCE_PRECEDENCE` gains `wikidata` (structured, mid-trust — below
   the authoritative/vendor sources, above the LLM tier) and `perplexity` + `google` (LLM tier, with
   `llm`); `registry.fill_specs`/`validate_fill_specs` updated so the resolved `gics_scd` chain still
   validates as a complete, strictly-ordered cover. (The opinion matrix is precedence-independent — it
   stores all opinions; precedence only resolves `gics_scd`.)
7. **Detail surfaces the full matrix.** `gateway.security_detail()`'s `classifications` now reads
   `gics_source_opinion` (every source's opinion for the figi), each row flagged `effective` when it
   matches the `gics_scd` precedence-winner's source. The detail "Classification by source" table
   renders the full multi-row matrix. The `gics_scd`-based resolved `sector`/`industry`/`sub_industry`/
   `source` are unchanged.
8. **Tests + no regressions.** DB-free unit tests: the wikidata + perplexity + google sources (fake HTTP
   client: sector/crosswalk mapping, GICS-validation, unmapped, per-entity isolation, no-key-skips for
   the keyed two, circuit-breaker); the opinion-store SCD writer (insert / unchanged no-op / change
   close+insert / multi-source coexistence for one figi); the run-all pass (each source fed ALL
   identities; keyed sources skip without a key); the gateway reading the opinion store (multi-row +
   effective flag). `gics_scd`, the heatmap, and `validate` unchanged; existing classification tests stay
   green. No new runtime dependency (stdlib `urllib`; FMP/Perplexity/Google keyed; LLM artifact-based).
9. **Live verification (what's possible in-env).** The keyless sources (financedatabase, b3, sec_sic,
   yahoo_profile, **wikidata**) populate a REAL multi-source matrix over the universe; `sym classify-opinions`
   reports per-source coverage; the detail view shows ≥2 opinions for names multiple sources cover
   (e.g. financedatabase + wikidata). FMP/Perplexity/Google verified dormant (clean "skipped — no key"
   lines). Honest ledger: the keyed sources are not live-verified (no keys) — like FMP today.

## Tasks / Subtasks

- [x] **Task 1 — `gics_source_opinion` migration** (AC: 1) — sqitch deploy/revert/verify + plan entry;
  table mirrors `gics_scd` levels + `source` + validity; EXCLUDE on `(composite_figi, source)` +
  daterange; FK; indexes. Deploy via the `sqitch/sqitch` Docker image (no local sqitch — see
  `reference-sqitch-deploy-docker`).
- [x] **Task 2 — opinion-store SCD writer + run-all-sources pass** (AC: 2) — in `classification/`:
  `apply_source_opinions(conn, source, plans)` (SCD close+insert per (figi, source), idempotent) +
  `run_opinion_matrix(conn, *, fmp_enabled, llm_enabled, perplexity_enabled, google_enabled)` that
  feeds `read_active_identities(conn)` to every gated source and writes each. New CLI
  `sym classify-opinions` (or `sym classify --opinions`) — explicit, NOT in `eod.py`.
- [x] **Task 3 — Wikidata source (keyless, LIVE)** (AC: 3) — `wikidata.py`: SPARQL client + the
  Wikidata-industry→GICS crosswalk + `WikidataGicsSource`; fake-client unit tests + a live smoke
  (Apple→Information Technology). This is the source that actually runs in-env.
- [x] **Task 4 — Perplexity source (keyed, dormant)** (AC: 4) — `perplexity.py` + fake-client unit tests.
- [x] **Task 5 — Google Gemini source (keyed, dormant)** (AC: 5) — `google_gemini.py` + fake-client tests.
- [x] **Task 6 — precedence + registry** (AC: 6) — add `wikidata`/`perplexity`/`google` to
  `SOURCE_PRECEDENCE`; update `fill_specs`/`validate_fill_specs`; keep the resolved-chain invariant green.
- [x] **Task 7 — surface in detail** (AC: 7) — `gateway.security_detail()` reads `gics_source_opinion`
  for `classifications`, flags `effective` vs the `gics_scd` winner. Frontend already renders the table
  (explorer-enrichment) — verify multi-row; no model shape change (`ClassificationBySource` already
  carries `source/sector/industry/sub_industry/effective`).
- [x] **Task 8 — tests + verify** (AC: 8, 9) — unit suites above; live `sym classify-opinions`
  (keyless sources incl. wikidata populate the matrix); confirm detail shows ≥2 opinions for a covered
  name; FMP/Perplexity/Google skip cleanly; `gics_scd`/heatmap/validate unchanged. `uv run pytest` + ruff green.

## Dev Notes

### Current state of files (read in story prep — exact anchors)

- **`packages/sym/src/sym/classification/gics.py`** — `GicsSource` protocol `fetch(Sequence[SecurityIdentity])
  -> dict[figi, GicsClassification]` (line 138-141); `read_active_identities` (line 234 — the "ALL active
  names" feed this story needs); `read_classifiable_identities` (307, the residual scope — NOT used by
  the opinion pass); `apply_classifications` (372, the gics_scd SCD writer — mirror its close+insert
  shape for the new opinion writer, but key the "current row" on (figi, **source**)); `SOURCE_PRECEDENCE`
  (40), `outranks` (50); `GicsClassification` (65), `SecurityIdentity` (122).
- **`packages/sym/src/sym/classification/registry.py`** — `FillSpec`, `fill_specs(llm_enabled)`,
  `run_fill_pass`, `run_classification_chain`, `validate_fill_specs` (import-time invariant). Add the two
  new sources here for the RESOLVED chain; the opinion pass is a separate orchestrator.
- **`packages/sym/src/sym/classification/llm.py`** — the LLM-source archetype to mirror for perplexity/
  google: sector validated ∈ 11 GICS at the boundary, MIC-guarded match, `source=...`, sector-only.
- **`packages/sym/src/sym/classification/yahoo_profile.py`** — `MAX_CONSECUTIVE_ERRORS` circuit-breaker
  + `last_short_circuited` + per-symbol `last_errors` (classification-robustness) — reuse this exact
  guard shape for the two HTTP LLM sources (they walk all N names; a key/quota outage must fail fast).
- **`packages/sym/migrations/deploy/gics_scd.sql`** — the table to mirror (levels + `source` +
  validity + `btree_gist` EXCLUDE). The new table's EXCLUDE adds `source WITH =` so sources coexist.
- **`services/api/src/qrp_api/modules/sym/gateway.py` `security_detail()`** — the `classifications`
  block currently does `DISTINCT ON (source)` over `gics_scd` (one opinion per source, mostly 1 row).
  Repoint it at `gics_source_opinion`; flag `effective` by matching the `gics_scd` effective `source`.
- **`services/api/.../router.py` `ClassificationBySource`** + **`apps/web/app/sym/securities/[figi]/page.tsx`**
  — the response model + UI table already exist (explorer-enrichment); no shape change needed.

### Key constraints (meticulous)

- **Never disturb the resolved classification.** `gics_scd`, `apply_classifications`, the fill chain,
  the heatmap, and `validate` are untouched. The opinion store is additive and read by the detail view
  only. A bug in the opinion pass must not be able to corrupt `gics_scd`.
- **Opinion store is keyed on (figi, source).** The EXCLUDE constraint is
  `composite_figi WITH =, source WITH =, daterange(valid_from, valid_to, '[)') WITH &&` — so source A
  and source B can both have an effective row for one company (the whole point), but a single source
  can't double-classify a company over one instant (point-in-time integrity per source).
- **Keyed/LLM sources are gated + dormant in-env.** FMP, Perplexity, Google run only when their key is
  set; they ship production-ready + unit-tested against a fake client and are NOT live-verified here
  (no keys — probed). Each emits one clean "skipped — no <KEY>" line. `dev-story` halts on a new runtime
  dependency — use stdlib `urllib` for both new HTTP sources (the sec_sic/yahoo/fmp posture).
- **LLM sources are low-trust + sector-only.** Validate the model's answer is one of the 11 GICS
  sectors at the boundary (an off-taxonomy or hallucinated answer is recorded unmapped, never written
  as a sector). Industry/sub-industry stay NULL. `source` ∈ {`perplexity`, `google`}.
- **Circuit-breaker on the HTTP LLM sources.** Reuse `MAX_CONSECUTIVE_ERRORS` — a key-quota/outage
  storm over 2,180 names must short-circuit, not walk them all. Surface `last_short_circuited`.
- **Cost-bounded cadence.** The opinion pass is explicit/on-demand (`sym classify-opinions`), never the
  nightly EOD. Document the yahoo-over-all cost (~tens of minutes) + LLM per-call cost.

### Testing standards

- Sources: DB-free, fake HTTP client (mirror `test_classification_yahoo_profile.py` / `_fmp`): sector
  parse, GICS-sector validation, unmapped/no-answer, per-symbol isolation, no-key-skip, circuit-breaker.
- Opinion store: DB-free recording-conn (mirror the `_RecordingConn` in the classification tests) —
  insert, unchanged no-op, change→close+insert, and TWO sources coexisting for one figi.
- Run-all pass: monkeypatch the sources; assert each is fed ALL identities (not the residual) and that
  keyed sources skip without a key.
- Gateway: extend `services/api/tests/test_sym_explorer.py`'s `_DetailConn` to serve the opinion-store
  query; assert a ≥2-source `classifications` list with the right `effective` flag.

### Project Structure Notes

- New: `classification/perplexity.py`, `classification/google_gemini.py`, the opinion writer + pass +
  `sym classify-opinions` CLI, one sqitch migration (`gics_source_opinion`), and the gateway repoint.
- UPDATE: `gics.py` (`SOURCE_PRECEDENCE`), `registry.py` (`fill_specs`/`validate_fill_specs`),
  `gateway.security_detail()`. No frontend shape change (the table + model already exist).
- Deferred/ledger after this story: deriving `gics_scd` FROM the opinion store by precedence (a clean
  future refactor — out of scope here to protect downstream); a disagreement report/validate check
  ("sources disagree on figi X"); FMP/Perplexity/Google live verification once keys exist.

### References

- [Source: packages/sym/src/sym/classification/gics.py:40,122,138,234,307,372] — protocol, identities, precedence, SCD writer.
- [Source: packages/sym/src/sym/classification/registry.py] — fill chain + validate_fill_specs.
- [Source: packages/sym/src/sym/classification/llm.py] — LLM-source archetype (validate-at-boundary, MIC-guard).
- [Source: packages/sym/src/sym/classification/yahoo_profile.py] — circuit-breaker + per-symbol isolation to reuse.
- [Source: packages/sym/migrations/deploy/gics_scd.sql] — table shape to mirror (+ source in the EXCLUDE).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py security_detail()] — the `classifications` query to repoint.
- [Source: _bmad-output/implementation-artifacts/classification-multisource.md] — the 6-source design + the Google-no-API / Perplexity-is-an-LLM findings.
- [Source: _bmad-output/implementation-artifacts/explorer-enrichment.md] — the "Classification by source" model + UI already built.
- [Source: reference-sqitch-deploy-docker (memory)] — deploy migrations via the sqitch Docker image.
- [Source: probe 2026-06-18] — api.perplexity.ai 401 (keyed), generativelanguage.googleapis.com 403 (keyed); no keys in-env.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Amelia / bmad-dev-story)

### Debug Log References

- `uv run pytest` (sym) → **785 passed**; `uv run pytest` (api) → **103 passed**; ruff clean on all touched files.
- Live matrix proof (real DB): financedatabase + sec_sic + wikidata over a sample → AAPL/MSFT carry 3 agreeing opinions (all IT), JPM/XOM 2 (no ISIN → no wikidata), HON sec_sic-only.
- Live API: `GET /api/sym/securities/BBG000B9XRY4` (AAPL) → `classifications` = 3 rows (financedatabase effective, sec_sic + wikidata opinions).

### Completion Notes List (2026-06-18)

**Store (Task 1):** `gics_source_opinion` migration (deploy/revert/verify + plan), EXCLUDE keyed on
`(composite_figi, source)` so sources coexist; applied to the dev DB (idempotent). `gics_scd` untouched.

**Writer + pass (Task 2):** `classification/opinions.py` — `apply_source_opinions` (SCD per (figi,
source): insert / unchanged no-op / same-day update-in-place / later-day close+insert; per-row tx
isolation) + `OpinionSummary`. `registry.run_opinion_matrix` runs every gated source over
`read_active_identities` (now carries `mic` for the exchange-scoped sources) and writes each opinion;
a source erroring is isolated (can't corrupt gics_scd). New CLI `sym classify-opinions` (on-demand,
NOT in EOD).

**Sources (Tasks 3-5):** `wikidata.py` (keyless, SPARQL P452 + industry→GICS crosswalk + dominant-sector
mode — LIVE); `perplexity.py` (Sonar) + `google_gemini.py` (Gemini) on a shared `_llm_classifier.py`
base (answer→GICS validation, per-symbol isolation, circuit-breaker), keyed + dormant in-env.

**Precedence + registry (Task 6):** `SOURCE_PRECEDENCE` + `fill_specs`/`validate_fill_specs` extended to
9 sources (wikidata mid-trust above the LLM tier; perplexity/google in it) — the resolved gics_scd chain
also gains them as fill passes, still validates as a complete strictly-ordered cover.

**Surface (Task 7):** `gateway.security_detail()` `classifications` repointed at `gics_source_opinion`
(every source's opinion; `effective` = matches the resolved gics_scd source), with a fallback to the
single resolved row when the matrix isn't populated. No API model / frontend shape change
(`ClassificationBySource` already existed from explorer-enrichment).

**Tests (Task 8):** 3 new suites (wikidata crosswalk+fetch+breaker; LLM-http base+gating; opinion-store
SCD writer + run_opinion_matrix). Updated `test_classification.py` (precedence-set grew; `_RouterConn`
now 4-col for the `read_active_identities` mic add) and `test_sym_explorer.py` (`_DetailConn` serves the
opinion query + a matrix-empty fallback test).

**Honest ledger:** Wikidata is live-verified. FMP / Perplexity / Google are dormant in-env (no keys) —
shipped production-ready + unit-tested against fake clients, not live-verified (the FMP precedent). The
full universe matrix is one `sym classify-opinions` run away (slow: yahoo over ~2,180 names ≈ tens of
minutes) — the live proof populated a representative sample. Deferred (ledgered): deriving gics_scd FROM
the opinion store; a "sources disagree" validate check; keyed-source live verification once keys exist.

### File List

- `packages/sym/migrations/{deploy,revert,verify}/gics_source_opinion.sql` (NEW) + `migrations/sqitch.plan` (UPDATE)
- `packages/sym/src/sym/classification/opinions.py` (NEW) — opinion-store SCD writer + `OpinionSummary`.
- `packages/sym/src/sym/classification/wikidata.py` (NEW) — Wikidata SPARQL source + crosswalk.
- `packages/sym/src/sym/classification/_llm_classifier.py` (NEW) — shared LLM-http base.
- `packages/sym/src/sym/classification/perplexity.py` (NEW) — Perplexity Sonar source (keyed).
- `packages/sym/src/sym/classification/google_gemini.py` (NEW) — Google Gemini source (keyed).
- `packages/sym/src/sym/classification/gics.py` (UPDATE) — `SOURCE_PRECEDENCE` +3; `read_active_identities` +mic.
- `packages/sym/src/sym/classification/registry.py` (UPDATE) — fill_specs +3, renderers, `run_opinion_matrix`/`_opinion_specs`.
- `packages/sym/src/sym/cli.py` (UPDATE) — `sym classify-opinions` command.
- `services/api/src/qrp_api/modules/sym/gateway.py` (UPDATE) — `security_detail` reads the opinion matrix.
- `packages/sym/tests/test_classification_{wikidata,llm_http,opinions}.py` (NEW); `test_classification.py` + `services/api/tests/test_sym_explorer.py` (UPDATE).

### Change Log

- 2026-06-18: Implemented multi-source-classification-matrix (Tasks 1-8). New `gics_source_opinion` store
  + run-all-sources opinion pass (`sym classify-opinions`) + 3 new sources (Wikidata live; Perplexity +
  Google keyed/dormant — chosen over scraping). Detail "Classification by source" now multi-row.
  `gics_scd` untouched. 30 new tests; 785 sym + 103 api green; ruff clean; live-verified (AAPL shows 3
  source opinions). Status → done.
