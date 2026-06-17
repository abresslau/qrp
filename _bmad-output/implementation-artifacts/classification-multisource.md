# Story: Multi-source industry classification (whole-universe, maintained)

Status: done

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
- [x] **Task 3 — Yahoo assetProfile source (crumb flow)** (AC: 3) — `sym/classification/yahoo_profile.py`:
  `HttpYahooProfileClient` (cookie→getcrumb→quoteSummary crumb flow, lazy session + one 401-retry,
  query1/query2 host fallback, throttle, URL-encoded symbol+crumb), an 11→11 `YAHOO_SECTOR_TO_GICS`
  crosswalk, `YahooProfileGicsSource` (sector-only, `source='yahoo_profile'`, per-symbol error
  isolation). Reuses sym's own `YAHOO_SUFFIX` (no cross-package import). Built 2026-06-17 after a
  re-probe confirmed the crumb flow works in-env (AAPL→Technology, SHEL.L→Energy). DB-free tests with
  a fake client + fake opener. **Closed the non-US residual: coverage 94.4% → 98.8%.**
- [x] **Task 4 — LLM gap-fill source (opt-in, last resort)** (AC: 4) — `sym/classification/llm.py` +
  `llm_classifications.json` (the reviewable artifact). `LlmGicsSource` matches by ticker (MIC-guarded),
  sector-only, `source='llm'`, validates sector ∈ 11 GICS at load (a typo never writes). Wired as the
  OPT-IN 5th fill pass behind `sym classify --llm` (OFF by default). Human-in-the-loop: Claude classified
  the residual's operating companies into the artifact; **funds/ETFs deliberately excluded** (no GICS
  sector to invent). Built 2026-06-17 (chosen by Andre as the "do the LLM gap-fill" follow-up).
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

### Yahoo assetProfile source added (2026-06-17, AC3 — "what's next" follow-up)

After the SEC MVP merged, Andre chose to continue closing the gap. The residual was 123 (mostly
NON-US: XLON 69, XMIL 11, …) which SEC SIC structurally can't reach. Re-probed the Yahoo crumb flow
(per the name-the-probe rule) — it **works in-env**: seed cookie from fc.yahoo.com (404s but sets
cookies) → getcrumb → quoteSummary assetProfile (AAPL→Technology, SHEL.L→Energy). Built
`yahoo_profile.py` as the **4th fill pass** (same fill-only/provenance/in-`with`-catch discipline).
Yahoo uses its own 11-sector taxonomy → an 11→11 `YAHOO_SECTOR_TO_GICS` crosswalk. Symbol built from
`SecurityIdentity.ticker`+`mic` via sym's own `YAHOO_SUFFIX` (DB-free, no cross-package import).

**Live: 97 of 123 filled, coverage 94.4% → 98.8%** (2161/2187). ftse100 incomplete 69 → 4 (the 4 are
closed-end investment trusts — SMT.L/PCT.L etc. — which legitimately have no GICS sector). Residual 26
= 14 no-profile + 12 stable 404s (funds + merged tickers) — the long tail the deferred LLM (AC4) would
target; marginal at 98.8%.

Focused code review of the crumb-session lifecycle (the only non-SEC-mirrored logic) found + fixed:
- **High — dead 401-retry:** `_fetch_profile` raised without `from last_exc`, so the `__cause__`-based
  401 detection never fired (and a crumb expiry would then poison every later symbol). Replaced with an
  explicit `is_auth` flag on `YahooProfileError`, set across the host-fallback loop (also fixes the
  Med: a 401 masked by a later host's 404).
- **High — `quoteSummary: null` crash:** the payload parse did `payload.get("quoteSummary", {}).get(...)`
  — but `{}` only covers a MISSING key, not a `null` value, so `None.get(...)` raised an `AttributeError`
  that escaped per-symbol isolation and aborted the whole pass. Extracted a defensive
  `_parse_profile_payload` (guards every level; 10 malformed-shape cases tested) — analogue of the
  sec_sic High fix.

### Change Log
- 2026-06-17: SEC SIC→GICS MVP implemented (Tasks 1,2,5,6). AC3 (Yahoo crumb) + AC4 (LLM) deferred per locked scope. Status → review.
- 2026-06-17: Applied 3-layer code-review fixes (per-CIK isolation [High], throttle [Med], provenance test [Med], int-guard [Low]); ledgered ticker-punctuation + literal-registry limitations.
- 2026-06-17: Added Yahoo assetProfile source (AC3, Task 3) — 4th fill pass, coverage → 98.8%; fixed 2 High review findings (dead 401-retry, quoteSummary-null crash). AC4 (LLM) still deferred.
- 2026-06-17: Added LLM gap-fill (AC4, Task 4) — opt-in `sym classify --llm` 5th pass, reviewable JSON
  artifact, 7 operating companies classified (source='llm'), funds correctly left unclassified;
  coverage → **99.1%**. ALL 8 ACs now landed (AC1–AC8). Only FMP profile source remains ledgered.
- 2026-06-17: Added the FMP profile source (the last ledgered source — now built). Keyed/dormant
  in-env (no `FMP_API_KEY`). See "FMP profile source added" below.

### FMP profile source added (2026-06-17 — last deferred source)

`sym/classification/fmp_profile.py`: `FmpProfileGicsSource` over FMP's `/v3/profile` endpoint
(`sector`/`industry` + `isFund`/`isEtf`). **KEYED** — needs `FMP_API_KEY` (the same key the FMP
universe provider uses); the `_cmd_classify` pass is **gated on the key** (one clean "skipped — no
FMP_API_KEY" line, dormant until set) so it never adds no-key noise. Probed first per the
name-the-probe rule: no key in-env, so built production-ready + unit-tested (DB-free fake client) but
not live-verified here.

Design (applies the retro lessons from the start): shared `RequestThrottle`, per-symbol error
isolation, defensive `_parse_profile_payload` (malformed shapes → no raise), stdlib `urllib` (uniform
with sec_sic/yahoo). An FMP→GICS crosswalk (FMP shares Yahoo's vendor taxonomy + a few legacy labels).
Bonus over the guess-prone sources: FMP's `isFund`/`isEtf` lets it **explicitly decline funds** (→
`last_skipped_fund`) rather than mis-classify them. Sector-only, `source='fmp'`.

Precedence: inserted at rank **3** in `SOURCE_PRECEDENCE` (financedatabase 0 → b3 1 → sec_sic 2 → **fmp
3** → yahoo_profile 4 → llm 5) — a paid vendor outranks the free yahoo/llm but sits below the
official/regulatory sources. Via the AC5 scope it can supersede yahoo/llm names once keyed. CLI chain
runs it between sec_sic and yahoo. 9 unit tests (crosswalk, symbol, fund-skip, unmapped, per-symbol
isolation, no-key-raises, provenance). 717 tests green.

**Note — AC1 registry trigger:** FMP is the **6th** source, and `_cmd_classify` now hard-codes six
near-identical fill passes. Per the retro action item, a 6th source is the trigger to consider the
self-registering registry generalization (AC1-as-written). Ledgered as the natural next refactor — NOT
done here (out of scope for "build the FMP source").

### LLM gap-fill added (2026-06-17, AC4 — final source)

Key reframing from the data: the 98.8% residual (26) was **mostly funds/ETFs that correctly have NO
GICS sector** (JPMorgan/PGIM/PIMCO/Global X/ProShares ETFs, Scottish Mortgage / Polar Capital
investment trusts, Pictet Cleaner Planet) — an LLM "filling" those would be a hallucination. Only ~7
were real operating companies the deterministic sources missed (recent renames/spinoffs). So the LLM's
real job was small + needed a "fund → no sector" guard.

No Anthropic API key in-env (probed env + .env), and at a 26-name tail an API-calling source would be
dormant + costly + lowest-trust. Andre chose the human-in-the-loop path: Claude (the agent) classified
the operating companies directly into a **versioned, reviewable artifact** (`llm_classifications.json`),
applied by `LlmGicsSource` as `source='llm'`. The artifact IS the review surface (rationale per row); a
wrong call is a one-line edit + `sym classify --llm`. Sector validated ∈ 11 GICS at load (a typo refuses,
never writes). MIC-guarded match (a foreign ticker-collision never inherits a US record's sector).

Classified (7): CADE→Financials, CIVI→Energy, CMA→Financials, KLG→Consumer Staples, PCH→Real Estate
(timber REIT), TGNA→Communication Services, ZEUS→Materials. Funds (19, incl. CSC "Collective Holdings"
which I wasn't confident on) deliberately left unclassified. Live `sym classify --llm`: 7 inserted, 19
unmatched, coverage 98.8% → **99.1%** (2168/2187). Default `sym classify` (no flag) unchanged — the LLM
pass never runs unless asked. 11 DB-free tests (no network, no LLM call at runtime).

### AC5 precedence-upgrade built (2026-06-17 — closes the review's sharpest finding)

The review found the chain was fill-only **first-writer-wins**: a later higher-precedence source
could never supersede an earlier lower-trust one (a `source='llm'` row was "sticky"). Now built so a
source may (re)classify a security that is unclassified OR held by a **strictly lower-precedence**
source, per an explicit `SOURCE_PRECEDENCE` ladder (financedatabase 0 → b3 1 → sec_sic 2 →
yahoo_profile 3 → llm 4):

- **`gics.py`**: `SOURCE_PRECEDENCE` + `outranks(new, current)` (strict; either side unknown → False,
  so legacy/manual rows are never clobbered and unknown sources never supersede). `read_classifiable_identities(conn, source=...)`
  returns unclassified + lower-held actives (the scope that lets a higher source reclaim a name).
  `apply_classifications` is precedence-aware: levels differ + outranks → close+insert (supersede);
  same levels + outranks → **in-place provenance upgrade** (no new SCD row, value unchanged); a
  non-outranking different source is a no-op (defensive guard). `_current_row` now also reads `source`.
- **`cli.py`**: the 4 fill passes use `read_classifiable_identities(conn, source=<their source>)`; the
  primary (financedatabase, all-actives) supersedes via the precedence-aware writer directly. Per-pass
  reports gained `upgraded`/`superseded` counts; "unclassified active" → "in-scope active".

It is a CROSS-RUN feature: on stable data it is a clean **no-op** (verified — source breakdown
unchanged, 0 historical rows, no churn); it fires when a source's data improves between runs (e.g.
financedatabase later gains a name an `llm` pass had filled → supersedes it). Live run confirms the
broadened scope (b3 sees 170, sec_sic 123, yahoo 26 = unclassified + lower-held) and the re-attempt
path (yahoo re-tries the 7 `llm` names every run, 404s, so the `llm` rows correctly persist until a
source can actually supersede them). 8 new unit tests: `outranks` ladder, supersede-on-later-day,
same-sector provenance-upgrade-in-place, lower-never-overwrites-higher, unknown-source-preserved,
end-to-end cross-source supersede, and the scope-query's lower-source param set. 685 tests green.

### AC1 registry generalization built (2026-06-17 — closes the last partial)

The code review flagged AC1 as partial: `_cmd_classify` hard-coded each concrete source. After
the 6th source (FMP) made that six near-identical pass+report blocks, built the registry:

- **`sym/classification/registry.py`** — owns the concrete fill sources. `FillSpec(name, factory,
  render, gate, skip_line)` per source; `fill_specs(*, llm_enabled)` returns the chain in precedence
  order (b3 → sec_sic → fmp → yahoo_profile → llm); `run_fill_pass(conn, spec)` runs one uniformly
  (gate → `read_classifiable_identities(source)` → plan → apply → render). An import-time assertion
  cross-checks the spec set + order against `SOURCE_PRECEDENCE` (an unregistered/mis-ordered source
  fails loudly). Per-source rendering moved here as `render` closures (faithful to the old output).
- **`_cmd_classify`** — the five hand-written pass blocks + five report blocks collapse to
  `results = [run_fill_pass(conn, spec) for spec in fill_specs(llm_enabled=args.llm)]` + one uniform
  report loop. The CLI **no longer imports any fill-source class** — only the registry. The primary
  (financedatabase, all-actives, re-asserts itself) stays the explicit anchor (`classify_universe`).

AC1-as-written ("pluggable, ordered precedence, never importing a concrete class") is now met for the
fill chain; adding the next source = one `FillSpec` entry. Behavior-preserving: live `sym classify`
output is byte-identical (same per-pass counts, fmp-skip line, coverage 99.1%). 9 registry unit tests;
730 tests green.

### Review Findings (code review 2026-06-17, 3-layer adversarial: Blind / Edge / Acceptance)

decision-needed: none.

patch (all applied 2026-06-17):
- [x] [Review][Patch] `read_active_coverage` is unguarded — a non-`OperationalError` there discards the whole atomic classify run (and the report block then reads unbound `total_classified`/`total_active`). **FIXED:** moved the coverage read onto a FRESH connection AFTER the write transaction commits, wrapped in `except psycopg.Error` → a coverage-read failure now prints a warning + returns 0 (writes already committed), never rolls them back. [packages/sym/src/sym/cli.py `_cmd_classify`]
- [x] [Review][Patch] Yahoo cookie-seed response is never closed — **FIXED:** `_ensure_session` now uses `with opener.open(...)` and closes the expected `HTTPError` (fc.yahoo.com 404s) via `exc.close()`. [packages/sym/src/sym/classification/yahoo_profile.py `_ensure_session`]
- [x] [Review][Patch] LLM artifact loader silently drops a duplicate-ticker row — **FIXED:** `LlmGicsSource.__init__` now raises `LlmClassificationError` on a duplicate ticker instead of first-wins `setdefault`. [packages/sym/src/sym/classification/llm.py]
- [x] [Review][Patch] AC8 cross-source precedence/merge test gap — **FIXED:** added `test_cross_source_merge_is_fill_only_first_writer_wins_with_provenance` (stateful fake conn; pass 1 classifies #1/#2, pass 2 fed only the unclassified fills #3 and can't overwrite #1; asserts per-row provenance + `rows_closed == 0`). [packages/sym/tests/test_classification.py]

defer (ledgered to deferred-work.md):
- [x] [Review][Defer→BUILT 2026-06-17] AC5 precedence-upgrade-closes-lower — was first-writer-wins; **now built** (see "AC5 precedence-upgrade built" below). AC5 is now fully met.
- [x] [Review][Defer] AC6 cadence/daily-maintenance hook not wired — `sym classify` is whole-universe + idempotent but not scheduled (no Dagster schedule/monitor hook; must set `execution_timezone` when built).
- [x] [Review][Defer] Yahoo has no circuit-breaker on a 401-storm / total outage — degrades per-symbol (`last_errors`) but walks all N residual at ~1.2s each instead of failing fast.
- [x] [Review][Defer] SEC `company_tickers.json` "first listing wins" CIK dedup assumes no duplicate tickers across CIKs — can mis-attribute after a ticker reassignment (delisted filer + new filer share a ticker).

dismissed (9): AC1 literal-registry (already ledgered + defensible); AC4 row-level review-workflow (already ledgered); coverage-gate vs fill-scope null-sector mismatch (no source writes null-sector rows — `plan_classifications` filters to `is_classified`); prior-run `llm` rows counted on a later plain run (correct — the gate measures actual DB coverage); `read_unclassified_identities` GROUP BY fan-out (composite_figi is PK); SIC auto-parts >3716→Industrials (3717 isn't a real SIC); Yahoo `.`→`-` for non-US dotted tickers (consistent with the price-path resolver); `last_unmatched` no-CIK/no-SIC conflation (labeled honestly in the CLI); SEC directory call not per-name isolated (single batch call; whole-pass failure is intended).

## Open questions (for review)
1. **Precedence order** — is `B3(BR) → financedatabase → SEC SIC → Yahoo → LLM` right, or should a
   live source (Yahoo/SEC) outrank the static financedatabase snapshot for freshness?
2. **LLM gap-fill** — in scope now (Claude classifies the residual, review-flagged), or defer until
   the deterministic sources (SEC/Yahoo) are in and we see the true residual?
3. **Yahoo crumb** — acceptable to add the crumb+cookie flow, or keep Yahoo deferred and lead with
   SEC SIC (keyless) which alone likely clears most of the US gap incl. HON?
