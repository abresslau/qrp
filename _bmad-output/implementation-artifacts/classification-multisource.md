# Story: Multi-source industry classification (whole-universe, maintained)

Status: ready-for-dev

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

- [ ] **Task 1 — Classification-source abstraction + registry** (AC: 1,5) — a `ClassificationSource`
  protocol (figi/ticker/mic → normalized GICS classification or None) + an archetype registry +
  ordered precedence + the SCD merge/provenance writer (extend the `gics.py` writer; keep its
  per-security `conn.transaction()` durability).
- [ ] **Task 2 — SEC SIC→GICS source** (AC: 2) — pull SIC from EDGAR (reuse the Q8.3 EDGAR client
  if present), a versioned SIC→GICS-sector crosswalk, normalize, register. DB-free tests with a
  captured EDGAR payload.
- [ ] **Task 3 — Yahoo assetProfile source (crumb flow)** (AC: 3) — getcrumb+cookie, quoteSummary
  assetProfile, Yahoo→GICS crosswalk; 401/no-crumb → source error (fall through). Reuse the QH.2
  `YAHOO_SUFFIX` symbol mapping. Tests monkeypatch the fetch + crumb.
- [ ] **Task 4 — LLM gap-fill source (opt-in, last resort)** (AC: 4) — classify residual names into
  a GICS sector with provenance + low trust; never override; review-flagged. Gated off by default.
- [ ] **Task 5 — Whole-universe maintenance command + cadence** (AC: 1,5,6) — `sym classify` extended
  (or a new `--scope all` / `classify-universe`) to run the precedence chain over all resolved
  members; coverage report by source; daily-maintenance hook.
- [ ] **Task 6 — Verify** (AC: 6,7) — `sym validate` (member-completeness GICS → ~0; HON classified),
  heatmap Unclassified tiles drop; `uv run pytest` green incl. the new source tests; ruff clean.

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

## Open questions (for review)
1. **Precedence order** — is `B3(BR) → financedatabase → SEC SIC → Yahoo → LLM` right, or should a
   live source (Yahoo/SEC) outrank the static financedatabase snapshot for freshness?
2. **LLM gap-fill** — in scope now (Claude classifies the residual, review-flagged), or defer until
   the deterministic sources (SEC/Yahoo) are in and we see the true residual?
3. **Yahoo crumb** — acceptable to add the crumb+cookie flow, or keep Yahoo deferred and lead with
   SEC SIC (keyless) which alone likely clears most of the US gap incl. HON?
