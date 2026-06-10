# Story U3.5: U3-wire — route the monitor through leaver-diff + gating; give the accuracy gate a runner

Status: review

## Story

As Andre (the operator),
I want `run_monitor`'s discoveries routed through the maintained-membership diff and the gating layer, and the accuracy gate runnable from the CLI,
so that Epic U3's promise — leavers detected, surprises gated, wrongness alarmed — actually holds on the live path instead of existing only as unwired modules.

## Background (why this story exists)

The 2026-06-10 project-wide code review (chunk 3) found that all three U3 safety mechanisms were **implemented and tested but never wired into `run_monitor`**:

1. `diff_identifier_sets` (`membership_diff.py`) has zero production callers → **no snapshot-sourced universe (B3, ETF, criteria, Wikipedia-current) can ever record a leaver**; members are permanent.
2. `stage_and_promote` (`gating.py`) is dead code on the live path → every discovered change is applied **directly to the append-only event log** on first sighting (`monitor.py` docstring admits it: "records discoveries directly (`applied`), leaving `proposed` at 0"). `membership_proposal` stays empty, so `sym universe review`'s pending pane and `sym universe confirm` have nothing to act on.
3. `run_accuracy_check` (`accuracy.py`) has **no runner** — no CLI, no schedule, no monitor hook.

Backlogged as **D1** in `deferred-work.md` (chunk-3 section). `docs/universe-maintenance.md` carries an honesty note describing exactly this gap — this story removes it.

In-review mitigations ALREADY APPLIED (do not redo): monitor idempotency guard (`_open_tokens`, skips re-stated joins/leaves), gating persistence rule fixed (`last_seen - first_seen`, not first-seen aging), `StageSummary.updated` honesty, criteria-universe `conn` injection, monitor session-snapped `as_of_date`, `enqueue_review` refresh, resolver determinism + OpenFIGI→local rescue.

## Acceptance Criteria

1. **Leaver detection (FR8 / U3.1 AC1 "derived by diffing snapshots"):**
   **Given** a universe whose provider output constitutes a full current snapshot, **When** `run_monitor` runs and a currently-open member (per the event log) is absent from the snapshot, **Then** a `leave` change (`POLL_BOUNDED`, effective `as_of_date`) is derived via `diff_identifier_sets` and routed through gating like any other discovery. Dated (EXACT) change events from API history keep flowing as today.
   **And** leaves are derived ONLY from provider output explicitly declared to be a full current snapshot (see Dev Notes — design decision 1); a partial/dated-only output must never synthesize leaves.

2. **Gating routing (NFR3 / U3.2 AC1+AC2 made live):**
   **Given** monitor-discovered changes (incl. derived leaves), **Then** `run_monitor` routes them through `stage_and_promote` instead of `append_change` directly:
   - churn above threshold → ALL of that run's changes staged as `churn_threshold` proposals, none auto-applied; the run's `MonitorSummary.status` = `MONITOR_GATED` (the currently-never-assigned constant) and `proposed` is populated;
   - non-surprising changes stage as `pending` and auto-promote per the existing persistence/corroboration rules (a poll-bounded change therefore lands in the log ~`DEFAULT_PERSIST_DAYS` after first sighting, or immediately on second-source corroboration);
   - `refresh_universe` (operator-explicit seed/refresh) keeps its current direct-append behavior — gating applies to the unattended monitor path only.

3. **Append paths rebuild the projection:**
   **Given** `promote_ready_proposals`, `confirm_proposal`, or `reverse_change` appends event(s), **Then** `resolve_universe_members` + `rebuild_projection` run for the affected universe (today an appended event stays invisible in `universe_membership` until an unrelated rebuild). Monitor path: resolve+rebuild when promoted > 0 (replacing the current `if joiners or leavers` trigger). The monitor must NOT pass `retry_unresolved=True` (OpenFIGI quota — that is `refresh_universe`'s prerogative).

4. **Accuracy runner (FR14 / U3.3 made runnable):**
   **Given** `sym universe accuracy <universe_id>`, **Then** it fetches the reference set from a configured independent source (universe `config.accuracy_reference` naming an archetype ≠ the primary; error if unconfigured or same-as-primary), runs `run_accuracy_check` with `proxy_tolerance=DEFAULT_PROXY_TOLERANCE` when the reference is an ETF proxy, prints the result, and exits 2 on alarm. Alarms surface in `universe review` (already wired via `accuracy_alarms`).
   **And** the token-scheme caveat is enforced: if the reference emits a different token scheme than the maintained set (e.g. `isin:` vs `ticker:`), the comparison resolves both sides to FIGIs first or refuses with a clear error — never a spurious ~1.0 divergence.

5. **Reverse CLI (U3.2 AC3 made operable):**
   **Given** `sym universe reverse <universe_id> <raw_identifier> <change> <effective_date>`, **Then** `gating.reverse_change` appends the corrective event and the projection is rebuilt; the command prints what was reversed. (Today reversal requires hand-written Python.)

6. **Monitor log honesty:** the `universe_monitor_log` row and `MonitorSummary` carry real `proposed`/`applied` splits and the `gated` status; the `monitor.py` module docstring's "this story records discoveries directly" paragraph is replaced by the real flow.

7. **Docs:** the honesty note in `docs/universe-maintenance.md` is removed and the ibov plan's "Gating: PLANNED" / "Leavers WILL BE tracked" lines are restated as live behavior. `deferred-work.md` D1 entry marked done (or removed).

8. **Tests:** DB-free tests cover — snapshot leaver derivation (member absent → leave staged), churn gate end-to-end through `run_monitor` (mass change → gated, nothing applied, status `gated`), persistence auto-promotion landing in the log + projection rebuild trigger, confirm/reverse triggering rebuild, accuracy CLI argument/exit-code paths, and the no-snapshot-no-leaves guard. Live verification on `ibov` (B3 snapshot): a synthetic member injected into the log disappears from B3's snapshot → leave proposed → promoted after persistence → interval closed.

## Tasks / Subtasks

- [x] Task 1: Snapshot declaration on providers (AC: 1)
  - [x] Add an explicit "this output is a full current snapshot" signal to the provider layer (recommended: `IndexSource`/`UniverseProvider` exposes `snapshot_tokens` — see design decision 1) for b3, etf_holdings, wikipedia-current, criteria, fmp (current-constituents half)
  - [x] DB-free tests per archetype: snapshot set surfaced; dated-history-only output declares none
- [x] Task 2: Route `run_monitor` through diff + gating (AC: 1, 2, 3, 6)
  - [x] Derive leaves: `open_tokens (already computed) - snapshot_tokens` → `diff_identifier_sets`-shaped leaves (reuse the existing `_open_tokens`; keep the existing join idempotency skip)
  - [x] Replace the direct `append_change` loop with `stage_and_promote(conn, uid, changes, current_count=len(open_tokens), as_of_date=...)`
  - [x] `MONITOR_GATED` status + `proposed`/`applied` counts on summary + log row; docstring rewrite
  - [x] resolve (no retry) + rebuild when promoted > 0
- [x] Task 3: Rebuild-after-append in gating (AC: 3)
  - [x] `confirm_proposal` / `reverse_change` trigger resolve+rebuild via the `_resolve_and_rebuild` helper (local resolver, no network); `promote_ready_proposals` stays rebuild-free — its only caller (`stage_and_promote` → monitor) rebuilds once per run when promoted > 0, not once per proposal
- [x] Task 4: Accuracy runner CLI (AC: 4)
  - [x] `config.accuracy_reference` read from `universe.config`; fetch reference via `get_index_source(archetype).fetch(...)` → snapshot tokens (falls back to `current_tokens_from_changes`)
  - [x] FIGI-level comparison fallback for cross-scheme references (maintained side from `universe_membership` figis; reference side via local resolver; unresolvable reference tokens stay divergent)
  - [x] `sym universe accuracy <id>` subcommand; exit 2 on alarm; wire `--threshold`
- [x] Task 5: Reverse CLI (AC: 5)
  - [x] `sym universe reverse <id> <raw_identifier> <join|leave> <effective_date>` → `reverse_change` + rebuild
- [x] Task 6: Docs + ledger (AC: 7)
- [x] Task 7: Test suite + live ibov verification (AC: 8)

## Dev Notes

### The wiring map (current state, post-2026-06-10 review patches)

| File | Current state | This story changes |
|---|---|---|
| `packages/sym/src/sym/universe/monitor.py` | `run_monitor` fetches provider changes, **skips** re-stated joins/leaves via `_open_tokens` (lines ~95-115, the idempotency guard), then `append_change`s directly; rebuilds only `if joiners or leavers`. `MONITOR_GATED` defined (line ~50) but never assigned. Criteria conn injection + session-snapped `as_of_date` already present. | Derive leaves; route through `stage_and_promote`; status/counters; rebuild on promoted>0. KEEP the `_open_tokens` join-skip (it prevents re-staging the whole membership daily). |
| `packages/sym/src/sym/universe/gating.py` | `stage_changes`/`is_promotable` (persistence = `last_seen - first_seen >= N` — fixed in review)/`promote_ready_proposals`/`confirm_proposal`/`reject_proposal`/`reverse_change`/`stage_and_promote` all working + tested (`test_universe_gating.py`, 6 tests). **No append path resolves/rebuilds.** | Add rebuild trigger after appends. |
| `packages/sym/src/sym/universe/membership_diff.py` | `diff_identifier_sets(previous, current, date, source)` pure + tested; token builders normalize (`BRK-B`→`BRK.B`). | Gains its first production caller. Diff on raw token strings as stored in the log — tokens are already normalized at mint time. |
| `packages/sym/src/sym/universe/accuracy.py` | `run_accuracy_check` writes `universe_accuracy_check` rows; `maintained_tokens` reads the PROJECTION (resolved members only — docstring documents this); `DEFAULT_PROXY_TOLERANCE` is caller-passed, never automatic; coalesced intervals now carry the LATEST token (review fix) so renames don't fake divergence. Token-scheme caveat documented in module docstring. | CLI runner + FIGI-level cross-scheme fallback. |
| `packages/sym/src/sym/universe/review.py` | Digest already assembles `pending_proposals` + `accuracy_alarms` — **no changes needed**; it lights up the moment proposals/checks exist. | Nothing (verify only). |
| `packages/sym/src/sym/cli.py` | `universe review` (`_cmd_universe_review`, ~line 980) and `universe confirm [--reject]` (~line 996, parser ~1274) already exist. No `accuracy`, no `reverse`. | Two new subcommands; `confirm` gains the rebuild side effect via Task 3. |
| `packages/sym/src/sym/universe/providers/*` | b3/etf_holdings/wikipedia emit current membership as JOIN events (b3: `POLL_BOUNDED` at `end`; wikipedia constituents: EXACT when Date-added present, else `POLL_BOUNDED`; fmp: current snapshot `POLL_BOUNDED` at `end` PLUS dated EXACT history). criteria emits `figi:` joins at `end`. | Task 1's snapshot declaration. |

### Design decision 1 — how the monitor knows "this is a full current snapshot"

Do **NOT** infer from `effective_date_precision`: Wikipedia's constituents table emits EXACT joins (Date-added) for current members, and FMP mixes a POLL_BOUNDED current snapshot with EXACT dated history in one output. Precision is about *date confidence*, not *set completeness*.

**Recommended:** make the snapshot set explicit at the source. Options in order of preference:
1. `IndexSource.fetch` keeps returning `list[MembershipChange]`, and sources additionally expose `last_snapshot_tokens: set[str] | None` populated during fetch (b3: `parse_portfolio_tokens` output; etf: holdings token set; wikipedia: constituents-table tokens; fmp: `_changes_from_current` tokens; criteria: the figi set). `IndexProvider.members` propagates the winning source's set; `run_monitor` reads it. Simple, no signature break.
2. A `fetch_snapshot()` second method — cleaner contract, more churn.
Avoid returning tuples from `members()` — `refresh_universe` and tests share that signature.

A universe whose provider surfaces no snapshot set (None) derives **no leaves** — dated-event flow only. Never synthesize leaves from absence in a dated-history feed.

### Design decision 2 — gating policy (recorded choice)

ALL monitor-path changes route through staging, including EXACT-dated API events. Consequence: an S&P constituent change lands in the log ~`DEFAULT_PERSIST_DAYS` (2) after first sighting instead of same-day. This is the U3.2 AC's letter ("must persist N days or be confirmed by a second source") and the safe default for an unattended path; `refresh_universe` remains the same-day operator path. If same-day dated events prove necessary later, add an `exact_dated_bypass` flag — do not silently special-case now.

### Constraints (violating any of these is a defect)

1. **The event log is append-only with dedupe key `(universe_id, raw_identifier, change, effective_date)`** — `events.append_change` also validates token shape (poison guard). Staged→promoted events flow through `append_change` already (in `promote_ready_proposals`); never insert into `membership_event` directly.
2. **Derived leaves are `POLL_BOUNDED` at the monitor's `as_of_date`** (a snapshot only bounds the date to the polling interval) — exactly what `diff_identifier_sets` defaults to.
3. **Churn denominator** = current open membership (use `len(_open_tokens(...))`), not the change count.
4. **Monitor must not consume OpenFIGI quota retrying frozen-unresolved members** — call `resolve_universe_members` WITHOUT `retry_unresolved` (see its docstring; refresh sets it True deliberately).
5. **Import direction:** `gating.py` already imports from `events`; the rebuild helper needs `projection.rebuild_projection` + `resolution.resolve_universe_members` — both import-safe from `gating` (neither imports gating). `monitor.py` already imports both. Do not import `monitor` from `gating`.
6. **`conn.autocommit = True` per-step durability is the established project pattern** (see memory/psycopg gotcha) — `run_monitor` sets it; keep gating's writes on the same connection semantics.
7. **`as_of_date` canonical naming everywhere** (params, columns, CLI flags use `--as_of_date` / `start_date`/`end_date` for ranges).
8. **Build-forward universes** (ibov/ibx, membership starts at first refresh): the leaver diff works from the log's open set, so it is correct from day one — no pit special-casing needed.
9. **Schedules** (if you add any Dagster hook for accuracy): `execution_timezone` MUST be explicit — hard standing rule. Prefer NO new schedule in this story; the monitor cadence + CLI is enough.

### Testing standards (match the existing suite)

- DB-free fakes: `tests/test_universe_monitor.py` and `test_universe_gating.py` show the established `_FakeConn` pattern (SQL-substring dispatch, canned rows). Extend them — the monitor fake must now answer the `membership_proposal` INSERT/UPDATE and `DISTINCT ON membership_event` (open-tokens) queries.
- `test_universe_projection.py` has the `invert(project)==log` property test — don't break it.
- The full sym suite is 422 tests, runs in ~3s: `cd packages/sym && python -m pytest tests/ -q`. All must pass.
- Live verification (ibov) is an operator step — document the command sequence in the story's completion notes, mirroring `docs/universe-maintenance.md`'s build sequence.

### Previous-story intelligence

- U3.1 (`U3-1-maintenance-monitor.md`): deliberately shipped direct-append with the note that U3.2 "will route surprising ones to `proposed` instead" — that routing is THIS story. Its DB-free fake-provider test approach is the template.
- U3.2 (`U3-2-gating-corroboration.md`): the gating module's tests cover threshold/persistence/corroboration/reversal as PURE functions — your new tests cover the ROUTING, don't duplicate the decision-logic tests.
- Chunk-3 review (commits `b4bd6b7`, `312051f`, `0aa912e`): the monitor idempotency guard, the persistence fix, and provider parse guards landed there — read those diffs before touching the same lines.
- Known adjacent caveats on the ledger (do NOT scope-creep into them): snapshot-pin resolution watermark (D2), `correct`-event provenance redesign (D3), maintenance plans for the 12 undocumented universes (D4), criteria-universe evolution semantics.

### Project Structure Notes

- All changes live in `packages/sym/src/sym/universe/` + `packages/sym/src/sym/cli.py` + `docs/universe-maintenance.md` + tests. No new modules required except possibly nothing — prefer extending existing files.
- No schema changes: `membership_proposal`, `universe_accuracy_check`, `universe_monitor_log` already exist with the needed columns (incl. `proposed`, `last_seen_date`, `corroborating_sources`).

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Epic U3] — FR8/FR9/FR14, U3.1–U3.4 ACs
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#chunk 3] — D1 (this story), in-review mitigations list
- [Source: docs/universe-maintenance.md] — honesty note to remove; ibov plan to restate
- [Source: packages/sym/src/sym/universe/{monitor,gating,membership_diff,accuracy,review}.py] — current behavior as tabled above
- [Source: docs/data-conventions.md] — token shapes, SCD, naming conventions

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor per task.

### Debug Log References

- Task 1 RED: 6 failures in `test_universe_snapshot_tokens.py` (attribute absent); ETF test initially used raw CSV row keys — fixed to `parse_holdings_csv`'s normalized keys.
- Task 2/3 RED: 7 failures in `test_universe_monitor_routing.py`; first leaver-test fixture used 2 open members so the single derived leave was 50% churn and (correctly) gated — fixture rescaled to 20 members.
- Live ibov: baseline monitor success 0/0 (declared snapshot matched open membership exactly — no false leaves on first wired run).

### Completion Notes List

- **Task 1 (snapshot declaration):** every snapshot-shaped source (b3, etf_holdings, fmp current-half, wikipedia constituents-half, criteria) sets `last_snapshot_tokens` during fetch; dated-history output contributes nothing to it. `IndexProvider.members` resets to None then propagates the winning source's set. Design decision 1 option 1 (no signature break).
- **Task 2 (routing):** `run_monitor` derives leaves via `diff_identifier_sets(open_tokens, snapshot, as_of_date, source)` (LEAVE half only — joins keep coming from provider events), keeps the `_open_tokens` re-statement skip, and replaces direct append with `stage_and_promote(current_count=len(open_tokens))`. `MONITOR_GATED` assigned on surprising runs (`StageSummary.surprising` new field); `proposed`/`applied` split real; resolve (no `retry_unresolved`) + rebuild only when promoted > 0. Promotion heartbeat runs even with zero discoveries so prior proposals graduate.
- **Gating fix found during Task 2:** a POLL_BOUNDED re-sighting shifts its effective date every poll, so the quad dedupe key would mint a new proposal row daily and persistence would NEVER accrue. `stage_changes` now bumps the pending proposal by `(universe, raw, change)` triple for POLL_BOUNDED changes; EXACT keeps the quad key.
- **Task 3 (rebuild-after-append):** `_resolve_and_rebuild` helper (local resolver, no network; lazy imports to avoid cycles) wired into `confirm_proposal` and `reverse_change`. `promote_ready_proposals` deliberately does NOT rebuild per-proposal — its only call path (monitor via `stage_and_promote`) rebuilds once per run.
- **Task 4 (accuracy runner):** `run_configured_accuracy_check` validates `config.accuracy_reference` (must exist, must differ from primary `source_pref[0]`), fetches via `get_index_source(...)`, prefers the source's declared snapshot over `current_tokens_from_changes`, applies `DEFAULT_PROXY_TOLERANCE` automatically for `etf_holdings` references, and on token-scheme mismatch compares FIGI-level (maintained side from `universe_membership.composite_figi`; reference side via local resolver — unresolvable tokens stay in the set so they count toward divergence rather than vanish). `run_accuracy_check` gained optional `maintained=` and `AccuracyResult.reference_source`. CLI exits 2 on alarm, 1 on config/connection error.
- **Task 5 (reverse CLI):** `sym universe reverse <id> <token> <join|leave> <date>` → `reverse_change` (which now rebuilds). Dedupe-hit (corrective already recorded) exits 1 with a message.
- **Task 6 (docs):** honesty note replaced with the live-behavior paragraph; ibov plan's "Leavers WILL BE"/"Gating: PLANNED" restated as live; ledger D1 and the FIGI-level-comparison deferred finding marked done. No accuracy schedule added by design (constraint 9).
- **Task 7 (tests + live):** 29 new DB-free tests (6 snapshot + 10 routing + 13 accuracy/reverse); suite 422 → 451, all green; zero new lint. Live ibov: synthetic `ticker:ZZZTEST3@BVMF` join appended → monitor staged the derived leave (`proposed=1 applied=0`) → `first_seen` backdated 2 days → next monitor auto-promoted (`applied=1`, log event carries `promoted_from_proposal` provenance, proposal `confirmed/auto`) → `sym universe reverse` appended the corrective + rebuilt → accuracy CLI refused unconfigured ibov with exit 1 → synthetic rows deleted explicitly, projection rebuilt, monitor back to baseline 0/0 with 78 open members.
- Live-test observation (existing D3 territory, not a regression): after a `correct` event, `_open_tokens` treats the token as not-open (latest event ≠ join) while the projector toggles state — the known provenance-aware-correct redesign covers this.

### File List

- packages/sym/src/sym/universe/providers/b3.py (modified — `last_snapshot_tokens`)
- packages/sym/src/sym/universe/providers/etf_holdings.py (modified — `last_snapshot_tokens`)
- packages/sym/src/sym/universe/providers/fmp.py (modified — snapshot from current-constituents half only)
- packages/sym/src/sym/universe/providers/wikipedia.py (modified — snapshot from constituents table only)
- packages/sym/src/sym/universe/providers/criteria.py (modified — `last_snapshot_tokens`)
- packages/sym/src/sym/universe/providers/index_provider.py (modified — propagate winning source's snapshot)
- packages/sym/src/sym/universe/monitor.py (modified — diff + gating routing, MONITOR_GATED, docstrings)
- packages/sym/src/sym/universe/gating.py (modified — POLL_BOUNDED triple-key bump, `StageSummary.surprising`, `_resolve_and_rebuild` in confirm/reverse)
- packages/sym/src/sym/universe/accuracy.py (modified — `run_configured_accuracy_check`, FIGI fallback, `reference_source`, `maintained=` param)
- packages/sym/src/sym/cli.py (modified — `universe accuracy` + `universe reverse` subcommands)
- packages/sym/tests/test_universe_snapshot_tokens.py (new)
- packages/sym/tests/test_universe_monitor_routing.py (new)
- packages/sym/tests/test_universe_accuracy_runner.py (new)
- docs/universe-maintenance.md (modified — honesty note removed, live behavior restated)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D1 + FIGI-comparison finding marked done)

### Change Log

- 2026-06-10: Story implemented end-to-end (Tasks 1-7), suite 451 green, live ibov verification passed. Status → review.
