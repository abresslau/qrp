# Story S.1: Durable review surfaces — per-flag price reviews + persistent FX rejections (schema batch I)

Status: done

## Story

As Andre (the operator),
I want price-anomaly flags that can't clobber each other and FX plausibility rejections that survive the process that printed them,
so that the two review surfaces the warehouse already depends on are durable: an audit divergence can't erase an unreviewed price-jump flag, and a peg-break that wedges the FX band is a visible, resolvable queue item instead of a console line nobody saw.

## Background (ledger items, verified live)

1. **Multi-flag clobber (chunk-5 ledger):** `prices_review`'s PK is `(composite_figi, session_date)` — one flag per date. The audit writer's upsert (`pipeline.py:444`) SETs `flag_type = EXCLUDED.flag_type ... WHERE NOT reviewed`: an unreviewed `price_jump` is silently REPLACED by a later `sweep_divergence` (and vice versa for the ingest writer). `pct_move` also means different things per type (signed day-move vs unsigned relative divergence) with nothing recording which.
2. **FX rejections evaporate (chunk-5 ledger, FX NFR4):** `load_fx` rejections (non-positive, band-exceeded) live only in `FxLoadSummary.flagged` — printed, never stored. After a GENUINE >50% move (peg break), `prev` never advances, so every subsequent observation is rejected forever — the band wedges until an operator happens to read a console line. There is no review row, no resolution path, no un-wedge mechanism.

Out of scope (stay parked, both conditional): the `membership_event` dedupe nonce (needs a same-date re-assertion after a reversal — hasn't happened) and the sequence-based resolution watermark (pins have no production callers).

## Acceptance Criteria

1. **Per-flag rows:** `prices_review`'s PK becomes `(composite_figi, session_date, flag_type)` (sym sqitch migration); both writers upsert on the new key; an audit divergence and a price-jump flag for the same (figi, date) COEXIST. The same-type re-flag still updates detail/pct while unreviewed (the existing idempotency).
2. **`pct_move` semantics recorded:** per-type meaning documented in the column COMMENT (price_jump: signed day-over-day; sweep_divergence: unsigned relative) — the value is intentionally type-scoped, not a bug to normalize.
3. **Gate unchanged:** the returns-gate reader (any unreviewed flag blocks the date) keeps its semantics under multiple rows per date (DISTINCT).
4. **FX rejections persist:** new `fx_rate_review` table (sym sqitch): quote currency, `as_of_date`, rejected rate, prior rate, relative move, source, reason (`non_positive` | `band_exceeded`), the prices_review-style reviewed/resolution pattern; `load_fx` writes a row per rejection (one OPEN row per (quote, date, source) — re-runs refresh, never duplicate); the in-memory `flagged` list stays for the CLI print.
5. **Un-wedge path:** `sym fx review` lists open rejections; `sym fx review --accept <id>` inserts the rejected rate into `fx_rate` (the steward vouches for it — the band's `prev` then advances naturally on the next load) and closes the row; `--reject <id>` closes it as vendor garbage. Accept/reject exit codes + clear messages.
6. **Visibility:** `check_fx_coverage` WARNs when open FX rejections exist (the validate suite is the operator's daily surface).
7. **Tests + live:** DB-free tests for both writers' new conflict keys, coexisting flags, the gate reader, rejection persistence, accept-inserts-rate, reject-closes; migrations deployed via the Docker sqitch flow; live round-trip — synthetic FX rejection → `fx review` lists it → `--accept` → rate present in `fx_rate` → cleanup; ledger updated.

## Tasks / Subtasks

- [x] Task 1: Migrations (AC: 1, 2, 4) — `prices_review_per_flag` (PK → 3-column; type-scoped `pct_move` COMMENT) + `fx_rate_review` (one-open-row partial unique index); deployed + verified via Docker sqitch
- [x] Task 2: prices_review writers + gate reader (AC: 1, 3) — both upserts on the 3-column key, neither overwrites `flag_type`; `resolve_review` gains an optional `flag_type` target; gate reads DISTINCT
- [x] Task 3: FX rejection persistence + resolve API (AC: 4, 5) — `_record_rejection` in `load_fx` (both kinds, prior/relative recorded); new `fx/review.py` (`list_fx_reviews`, `resolve_fx_review` — atomic, concurrent-close guard, typed FK refusal)
- [x] Task 4: CLI `sym fx review [--all|--accept ID|--reject ID]` (AC: 5) + `fx_coverage` WARN on open rejections (AC: 6)
- [x] Task 5: Tests + live round-trip + ledger (AC: 7) — 9 new tests (+2 fake updates); live: synthetic rejection → listed → unknown-ccy accept refused TYPED (row stayed open — the FK live-test found this gap and it was fixed in-flight) → real-ccy accept landed the rate in `fx_rate` + closed the row → cleanup → queue empty, fx_coverage at baseline

## Dev Notes

### Constraints

1. **`fx_rate` stays immutable-insert** — accept writes through the same `INSERT ... ON CONFLICT DO NOTHING` discipline; never UPDATE a stored rate.
2. **The PK swap migration must preserve existing rows** (live table has flags) — `ALTER TABLE ... DROP CONSTRAINT pk, ADD PRIMARY KEY (figi, session_date, flag_type)`; existing (figi,date) rows are unique under the wider key by construction.
3. **`as_of_date` canonical naming** in the new table and APIs.
4. **One OPEN row per FX rejection key** — partial unique index (`WHERE NOT reviewed`), the securities_review_queue pattern; closing frees the key.
5. **Resolution pattern parity:** `reviewed = (resolution IS NOT NULL)` CHECK, same as prices_review.
6. **Docker sqitch flow** for deployment; verify scripts included.
7. **The session's services are running** — no API impact expected (sym-internal), no restart needed unless CLI freshness matters for live tests (CLI runs from source).

### Previous-story intelligence

- Today's review rounds repeatedly flagged secure/correct-by-accident states — document per-type `pct_move` semantics and the accept-un-wedges-band mechanism explicitly.
- Live-verification pattern: synthetic rows + explicit cleanup (test-row rule).
- Suite baselines: sym 531; lint 18 pre-existing. Docker is UP (O.2 deployed through it).

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md — chunk-5 multi-flag + FX-rejection entries]
- [Source: packages/sym/migrations/deploy/prices_review.sql + prices_review_sweep_flag.sql]
- [Source: packages/sym/src/sym/{ingest/pipeline.py:444, fx/ingest.py:95-128, returns/loader.py:227}]

### Review Findings (code review 2026-06-10, commit c45f33d — ALL RESOLVED)

- [x] [Review][Patch] [HIGH] Accept is honest end-to-end: RETURNING-checked insert → `(resolution, rate_inserted)` tuple; the CLI distinguishes "rate inserted" / "ALREADY stored, nothing inserted, row closed"; row SELECT moved inside the transaction; `non_positive` accepts refused typed. ALL THREE paths verified live (free date landed 5.31; collide left 5.163 untouched with the honest message; non-positive exit 1 then clean reject) [fx/review.py, cli.py]
- [x] [Review][Patch] [HIGH] The queue drains: `fx_rate_review_superseded` migration widens the resolution CHECK; `load_fx` closes open rejections whose key it successfully inserts (`superseded`, existence-gated per currency so the clean path pays one probe); oldest-first guidance in the CLI help + docstring [fx/ingest.py, migration]
- [x] [Review][Patch] `resolve_review` refuses ambiguity (>1 open flags, no type) and unknown flag types — the relocated clobber is closed (tested) [ingest/prices.py]
- [x] [Review][Patch] CONFIRMED + FIXED: the overwrite path deleted `prices_raw` BEFORE the review rows that FK-reference it — any flag in the window aborted the overwrite (pre-existing; per-flag rows widened it). Review rows now delete first [ingest/pipeline.py]
- [x] [Review][Patch] `fx_coverage` counts open rejections BEFORE the early returns; the warning rides all three paths [validate/fx.py]
- [x] [Review][Patch] Tests: FK-refusal regression (insert raises → typed error, row NOT closed); honest-accept both outcomes; supersede drain; ambiguity/unknown-type guards; predicates aligned; the no-op DISTINCT grep dropped (SQL keyword stays) — suite 540 → 544 [tests]
- [x] [Review][Patch] Migrations polished: verify scripts anchored to `conrelid` + the partial unique index checked; the per-flag revert gained a mechanical keep-latest dedupe pre-pass; `relative_move` (RATIO)/`prior_rate`/`resolution` COMMENTs ride the superseded migration — deployed + verified [migrations]
- Dismissed (4): pre-migration `UndefinedTable` guard on `_record_rejection` (single environment; both changes registered in the sqitch registry); stale-flag-type accumulation tightening the gate (the conservative direction is CORRECT — an outstanding finding needs review; the resolve path exists); the WARN counting all sources/history (single canonical source today; supersede shrinks the queue toward zero); source-text test style in general (the project's DB-free convention — only the incoherent/no-op instances are culled).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code.

### Debug Log References

- The live accept test hit `fx_rate`'s currency FK with a synthetic 'ZZZ' currency — a REAL gap (an unknown-currency accept would have tracebacked): wrapped as a typed `FxReviewError`, transaction rolls back, the row stays open. Re-tested with BRL on a rate-free date: clean accept, rate landed, cleanup verified.
- Two pre-existing fx test fakes needed the new queries (rejection INSERT dispatch; open-rejections count); net lint went BELOW baseline (17 vs 18 — a docstring rewrite incidentally fixed an old E501).

### Completion Notes List

- **Clobber fixed structurally:** the PK widened to `(figi, session_date, flag_type)`; both writers' conflict targets follow and neither overwrites `flag_type` — an audit divergence and a price jump about the same bar now coexist while both await review. `pct_move`'s per-type meaning (signed day-move vs unsigned divergence) is recorded in the column COMMENT — type-scoped by design, not normalized away.
- **FX rejections durable + resolvable:** one OPEN row per (quote, date, source) — daily re-runs refresh; ACCEPT inserts the rate through the same immutable-insert discipline (`ON CONFLICT DO NOTHING`), after which the band's `prev` advances naturally on the next load — the un-wedge mechanism is the normal data path, not a special case. REJECT closes as vendor garbage. `fx_coverage` surfaces open rejections in the daily validate.
- Out of scope (still parked, both conditional): the membership_event dedupe nonce; the sequence-based resolution watermark.

### File List

- packages/sym/migrations/{deploy,revert,verify}/prices_review_per_flag.sql + fx_rate_review.sql + sqitch.plan (2 migrations)
- packages/sym/src/sym/ingest/prices.py (modified — conflict key, resolve_review flag_type)
- packages/sym/src/sym/ingest/pipeline.py (modified — audit conflict key)
- packages/sym/src/sym/returns/loader.py (modified — DISTINCT gate read)
- packages/sym/src/sym/fx/ingest.py (modified — _record_rejection)
- packages/sym/src/sym/fx/review.py (new — list/resolve API)
- packages/sym/src/sym/cli.py (modified — `sym fx review`)
- packages/sym/src/sym/validate/fx.py (modified — open-rejections WARN)
- packages/sym/tests/test_durable_reviews.py (new — 9 tests); test_fx_ingest.py + test_fx_coverage.py (fake updates)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — both items done)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-5); suite 531 → 540 green; lint 18 → 17 (below baseline); live FX round-trip verified incl. the FK-refusal gap found and fixed during the live test itself. Status → review.
- 2026-06-10: Code review (3 adversarial layers; the Auditor LIVE-PROVED the false-message finding with a cleanly-reverted synthetic write) — 7 patches applied (2 HIGH: honest accept outcomes verified live on all three paths; the superseded drain so peg-break queues empty themselves; plus the pre-existing overwrite-path FK-ordering bug confirmed and fixed), 4 dismissed. Suite 540 → 544 green. Status → done.
