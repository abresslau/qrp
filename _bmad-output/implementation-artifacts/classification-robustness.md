# Story: Classification robustness — outage short-circuit, SEC dedup, CLI-loop test coverage

Status: done

<!-- Created via bmad-create-story (2026-06-18). Bundles the still-open deferred items from
classification-multisource.md's two code reviews ("classification-multisource 2026-06-17" and
"registry refactor 2026-06-17b") into one hardening story. Source: deferred-work.md lines 4-5
and 25-26. NOT part of any epic decomposition — like the rest of the classification track, it
lives as a standalone artifact (sprint-status.yaml's DERIVATION NOTE: classification stories are
tracked inline, not in the epic files). -->

## Story

As the **operator of QRP**,
I want **the multi-source classification chain to fail fast on a source outage, attribute SEC
classifications to the correct (active) filer when a ticker has been reassigned across CIKs, and
have the `sym classify` CLI loop + its per-pass report pinned by tests**,
so that **a nightly EOD `classify` step can't burn minutes walking a dead source, a stale CIK can't
silently mis-sector a name, and a future wording/branch change in the report is caught automatically
instead of drifting (as the "— not queried" drift already did once)**.

## Why (the open robustness gaps)

The multi-source classification chain (`classification-multisource.md`, all 8 ACs landed, on `main`)
is functionally complete and now runs unattended in the daily EOD. Its code reviews left four
**robustness** items deferred — none break a passing test today, all are real:

1. **Yahoo has no circuit-breaker on a 401-storm / total outage.** `YahooProfileGicsSource.fetch`
   isolates errors per-symbol (`last_errors`) — correct for a single bad name — but on a *sustained*
   Yahoo outage (crumb flow dies, every symbol 401s) it walks **all N residual names at ~1.2s each**
   (0.3s throttle + 2 host attempts + a re-establish-and-retry on the 401) instead of giving up after
   K consecutive failures. At owner scale the residual is small (~26), but it's wired into the
   **nightly EOD** now — a Yahoo outage shouldn't cost minutes of dead walking every night.
2. **SEC `company_tickers.json` "first listing wins" CIK dedup.** `HttpSecClient.company_ciks` keeps
   the **first** directory row per ticker (`out.setdefault(ticker, …)`), assuming no duplicate tickers
   across CIKs. But SEC *can* carry the same ticker for two CIKs after a ticker reassignment (an old
   delisted filer + a new active filer), so a **stale CIK's SIC** could be attributed to the new name.
   Rare + SIC→sector is coarse enough to usually agree, but it's a silent-wrong-data risk.
3. **No `_cmd_classify` loop-integration test.** The registry units (`run_fill_pass` run/skip/error/
   empty) + the live smoke cover the pieces, but nothing tests the CLI's
   `run_classification_chain` → **report-printing loop** end to end: the four per-pass branches
   (skipped→skip_line, error→stderr, empty→"— not queried", success→lines) on the **right stream**
   (stdout vs stderr), plus the coverage-gate exit codes (0 / 2 / coverage-read-failed→0).
4. **No output-equivalence / snapshot regression test.** There's no golden snapshot pinning the
   per-pass report lines, so a future wording change (like the empty-scope "— not queried" drift this
   review *caught by hand*) wouldn't be caught automatically.

**Out of scope (blocked, ledgered):** the **FMP non-US symbol-format spot-check**
(`fmp_symbol_for_identity` reuses `YAHOO_SUFFIX` — US is exact, non-US is a best-guess) needs a live
`FMP_API_KEY` to verify against FMP's real symbol scheme. No key in-env → leave ledgered, do NOT
guess at it here.

## Acceptance Criteria

1. **Yahoo consecutive-failure short-circuit.** `YahooProfileGicsSource.fetch` stops attempting
   further symbols after **K consecutive fetch errors** (`YahooProfileError` — the outage signal),
   rather than walking the whole residual. The K threshold is a named constant (default ~5),
   resettable: a *success or a clean no-profile* between errors resets the counter (so a few scattered
   bad names never trip it — only a genuine run of failures does). When tripped, the remaining
   identities are recorded on a new side-channel (e.g. `last_short_circuited: list[str]`) and the
   already-found classifications are returned intact (fill-only, partial result is fine — the next
   nightly run retries). A normal `last_unmatched` (Yahoo returned no profile) is **not** an error and
   must **not** count toward the breaker.
2. **Short-circuit is observable.** The `yahoo_profile` pass report (`registry._render_yahoo`) gains a
   line/count when the breaker tripped (e.g. `short-circuited after N consecutive errors; M not
   attempted`), so an outage is visible in the CLI and the EOD `classify` status line — never a silent
   "fewer filled than expected".
3. **SEC duplicate-ticker resolution.** `HttpSecClient.company_ciks` no longer blindly first-wins on a
   duplicate ticker. When `company_tickers.json` carries **>1 CIK for the same ticker**, it resolves to
   the **active / most-recent filer** rather than directory order (recommended: collect all CIKs per
   ticker; for the rare ticker with a collision, prefer the filer whose `submissions` still lists the
   ticker / has the most recent filing — bounded to only the colliding tickers so the common single-CIK
   path is unchanged and adds no extra calls). At minimum the ambiguity must be **surfaced** (a new
   side-channel, e.g. `last_ambiguous_ticker: dict[ticker, list[cik]]`, reported by the caller) rather
   than silently resolved first-wins. Single-CIK tickers (the overwhelming majority) behave exactly as
   today.
4. **`_cmd_classify` loop-integration test.** A DB-free test (in `tests/test_cli.py`) that monkeypatches
   `run_classification_chain` to return a crafted `(primary_summary, [PassResult, …])` covering **all
   four** per-pass branches (skipped-with-line, skipped-silent, error, empty, success-with-lines) +
   `read_active_coverage`, invokes `_cmd_classify`, and asserts via `capsys`: the success/empty/skip
   lines on **stdout**, the `… fill pass FAILED …` line on **stderr**, and the **exit code** for each of
   the three coverage outcomes (≥ threshold → 0; < threshold → 2; coverage-read raises `psycopg.Error`
   → prints "unavailable" + returns 0).
5. **Per-pass report golden/snapshot test.** A DB-free regression test that pins the rendered report
   lines for a **representative run** (each source's renderer fed crafted side-channels + a
   `ClassificationSummary`, OR the assembled `_cmd_classify` output) against a committed golden
   (inline expected block or a `tests/`-adjacent fixture). A wording change to any per-pass line — or
   the empty-scope "— not queried" line, or the new short-circuit line (AC #2) — fails this test.
6. **No regressions, no new dependency.** All existing classification tests stay green; the
   `financedatabase`/b3/sec_sic/fmp/yahoo/llm behaviour is unchanged on the happy path; `sym classify`
   and `sym eod --steps classify` still run identically (the breaker + dedup only change *outage* /
   *collision* behaviour). Stdlib `urllib` only — no new runtime dep (`dev-story` halts on one). `ruff`
   clean on touched code.

## Tasks / Subtasks

- [x] **Task 1 — Yahoo consecutive-failure circuit-breaker** (AC: 1, 2)
  - [x] In `sym/classification/yahoo_profile.py`, added `MAX_CONSECUTIVE_ERRORS = 5` and a
    `last_short_circuited: list[str]` side-channel (reset per `fetch`, alongside the existing four).
  - [x] In `YahooProfileGicsSource.fetch`, track a consecutive-error counter: increment on a caught
    `YahooProfileError`, **reset to 0** on any non-error outcome (hit or clean no-profile). When it
    reaches the threshold, stop the loop, append every *not-yet-attempted* identity's symbol to
    `last_short_circuited`, and return the `found` accumulated so far.
  - [x] In `sym/classification/registry.py` `_render_yahoo`, added the short-circuit count to the header
    `extra` + a detail line when `last_short_circuited` is non-empty.
  - [x] Tests in `tests/test_classification_yahoo_profile.py` (fake client): (a) K consecutive errors
    trips the breaker and the rest land in `last_short_circuited`; (b) errors interleaved with
    successes never trip it; (c) a clean no-profile resets the counter.

- [x] **Task 2 — SEC duplicate-ticker / CIK dedup** (AC: 3)
  - [x] In `sym/classification/sec_sic.py` `HttpSecClient.company_ciks`, replaced `setdefault`-first-wins:
    collect ALL candidate CIKs per ticker; one → use it (zero extra calls); >1 → `_resolve_active_cik`
    (prefers the filer whose `submissions` still lists the ticker, tie-broken by most-recent filing date;
    falls back to the first when submissions unreachable) + record on `last_ambiguous_ticker`.
  - [x] Threaded `last_ambiguous_ticker` through `SecSicGicsSource` (copied from the client via `getattr`
    so fakes still work) + `_render_sec` reports it.
  - [x] Tests in `tests/test_classification_sec_sic.py`: single-CIK path unchanged + no extra calls;
    duplicate resolves to the active filer; fallback-to-first when submissions unreadable; source
    surfaces the ambiguity.

- [x] **Task 3 — `_cmd_classify` loop-integration test** (AC: 4)
  - [x] In `tests/test_cli.py`, monkeypatch `run_classification_chain` + `read_active_coverage` + `connect`
    + `load_dotenv`; build `PassResult`s exercising all five branches (skip-with-line, skip-silent, error,
    empty, success); call `_cmd_classify`; assert stdout/stderr split via `capsys` + exit code for each
    coverage outcome (≥threshold→0 / <threshold→2 / read-raises→0). No DB, no network.

- [x] **Task 4 — Per-pass report golden/snapshot test** (AC: 5)
  - [x] New `tests/test_classification_report.py` renders all five `_render_*` closures with crafted
    `SimpleNamespace` side-channels and asserts the EXACT line lists (golden). Pins the new circuit-breaker
    line (+ its absence when not tripped) and the ambiguous-ticker line; the empty-scope "— not queried"
    line is pinned exactly in the Task 3 CLI test.

- [x] **Task 5 — Verify** (AC: 6)
  - [x] `uv run pytest` → **753 passed, 0 failed** (no pre-existing failure surfaced this run); `ruff check`
    clean on all touched files.
  - [x] `uv run sym eod --dry-run` still lists `classify` between `map` and `validate`; `sym classify --help`
    intact. Happy path unchanged by construction (breaker only fires on K consecutive errors; SEC dedup only
    changes the >1-CIK path; renderers add lines only when the new side-channels are non-empty — pinned by
    the no-circuit-breaker golden + the unchanged sec/yahoo registry tests).

## Dev Notes

### Current state of files being touched (read these first — done in story prep)

- **`packages/sym/src/sym/classification/yahoo_profile.py`** (UPDATE) — `YahooProfileGicsSource.fetch`
  (lines ~270-303) loops per-identity: builds the symbol, calls `client.sector_for_symbol`, and on a
  `YahooProfileError` records `last_errors[symbol]` and **continues**. That `continue` is exactly where
  the breaker belongs — the loop already has the per-symbol error path; add a consecutive counter around
  it. `HttpYahooProfileClient.sector_for_symbol` already does the 0.3s throttle + a one-shot 401
  re-establish+retry (the source of the ~1.2s/symbol cost), and `is_auth` on `YahooProfileError` already
  distinguishes a 401 — the breaker can count *all* errors or weight auth-errors; counting all
  consecutive errors is simplest and matches the "total outage" framing. Side-channels are reset at the
  top of `fetch` — add `last_short_circuited` to that reset block.
- **`packages/sym/src/sym/classification/sec_sic.py`** (UPDATE) — `HttpSecClient.company_ciks`
  (lines ~90-111) iterates `company_tickers.json` rows and does
  `out.setdefault(ticker, f"{int(cik_raw):010d}")` with the comment *"First listing wins; the directory
  has no duplicate-ticker rows."* — that assumption is the bug. The directory is `{idx: {ticker, cik_str,
  title}}`; it has no active/inactive flag, so resolving "active" needs a `submissions` recency check
  (the `sic_for_cik` endpoint already fetches submissions — recency lives in the same payload's
  `filings`/`tickers`). Keep the resolution **bounded to colliding tickers** so the common path adds zero
  calls. The `SecClient` Protocol (`company_ciks`/`sic_for_cik`) is the injection seam the tests use.
- **`packages/sym/src/sym/classification/registry.py`** (UPDATE — renderers) — `_render_yahoo`
  (lines ~129-143) and `_render_sec` (lines ~98-110) build the `extra` header string + detail lines from
  the source's side-channels. Add the new short-circuit / ambiguous-ticker counts here. `_header` (line
  ~70) is the shared format. These renderers are what the golden test (Task 4) pins.
- **`packages/sym/src/sym/cli.py` `_cmd_classify`** (READ — no logic change needed) — lines 203-280.
  It calls `run_classification_chain(conn, llm_enabled=args.llm)`, reads `read_active_coverage` on a
  **fresh** connection, prints the primary summary, loops `results` printing one of four branches per
  pass (skip_line / FAILED→stderr / "— not queried" / `r.lines`), then gates on
  `DEFAULT_COVERAGE_THRESHOLD` (return 2 below it, 0 above, 0 if coverage read failed). Task 3 tests this
  loop exactly as-is — no change to the CLI unless a new branch is needed.
- **`gics_scd` schema / SCD writer / `apply_classifications`** (NO CHANGE) — this story is source-side +
  test-side only. No migration, no write-path change, no frontend change.

### Key constraints

- **Fill-only is preserved.** Both the breaker (partial result) and the dedup (right CIK) keep every
  source fill-only and provenance-tagged — they change only *outage* and *collision* behaviour, never
  the happy path. A short-circuited Yahoo pass just fills fewer names this run; the next nightly retries
  (the residual is recomputed from `read_classifiable_identities` each run).
- **An error ≠ a no-profile.** The breaker counts `YahooProfileError` (fetch/auth failure), NOT
  `last_unmatched` (Yahoo cleanly returned no sector). Conflating them would trip the breaker on a run of
  legitimately-unclassifiable names (funds) and abort a healthy pass. This distinction is the crux of
  AC #1 — test it explicitly.
- **Bound the SEC dedup cost.** Don't add a `submissions` call for *every* ticker — only for the rare
  ticker with >1 directory CIK. The single-CIK path (essentially all tickers) must keep its current
  one-directory-call + one-submissions-call-per-name shape and SEC throttle (`min_interval=0.12s`,
  ~8 req/s under the 10/s ceiling).
- **DB-free tests.** Every test here mocks the injected client (`YahooProfileClient` / `SecClient`
  Protocols) or monkeypatches the `registry`/`gics` functions — no DB, no network, matching the existing
  `test_classification_*` suite. `_cmd_classify` is tested by stubbing `run_classification_chain` +
  `read_active_coverage`, not by standing up Postgres.
- **No new dependency** — stdlib `urllib` only (the QH.2/Q8.3/multi-source posture). `dev-story` halts on
  a new runtime dep.
- **FMP non-US spot-check stays out** — blocked on a live `FMP_API_KEY`; leave the deferred-work entry as
  is, don't touch `fmp_symbol_for_identity`.

### Testing standards

- Framework: `pytest`, run via `uv run pytest packages/sym` (per the classification stories). DB-free
  unit tests with injected fake clients / monkeypatched module functions; `capsys` for CLI stdout/stderr
  assertions. Name new tests `test_<behavior>` and make each **fail without its fix** (the project's
  pinned-fix discipline — see classification-multisource.md "tests pin the fix, not just the happy
  path").
- Existing test files to extend: `test_classification_yahoo_profile.py`, `test_classification_sec_sic.py`,
  `test_cli.py`, `test_classification_registry.py` (or a new `test_classification_report.py` for the
  golden).

### Project Structure Notes

- All changes live in `packages/sym/src/sym/classification/` (yahoo_profile.py, sec_sic.py, registry.py)
  + `packages/sym/tests/`. No CLI logic change expected (Task 3 only adds a test). No migration, no
  schema change, no frontend, no new package.
- Deferred/ledger after this story: the FMP non-US symbol-format spot-check (keyed) remains the only open
  classification item.

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — "code review of
  classification-multisource (2026-06-17)" lines 25-26 (Yahoo breaker, SEC dedup) + "registry refactor
  (2026-06-17b)" lines 4-5 (CLI-loop test, snapshot test) — the four items this story closes.
- [Source: _bmad-output/implementation-artifacts/classification-multisource.md] — the parent story;
  "Review Findings" sections list these as `[Review][Defer]`; design/precedence/provenance context.
- [Source: packages/sym/src/sym/classification/yahoo_profile.py#YahooProfileGicsSource.fetch] — the
  per-symbol loop + `last_errors` the breaker wraps; `HttpYahooProfileClient` throttle + 401 retry (the
  ~1.2s/symbol cost).
- [Source: packages/sym/src/sym/classification/sec_sic.py#HttpSecClient.company_ciks] — the
  `setdefault` first-wins dedup to fix; `SecClient` Protocol is the test seam.
- [Source: packages/sym/src/sym/classification/registry.py] — `_render_yahoo`/`_render_sec` (the report
  lines to extend + pin) + `run_fill_pass`/`run_classification_chain` (the orchestrator Task 3 stubs).
- [Source: packages/sym/src/sym/cli.py#_cmd_classify lines 203-280] — the report-printing loop +
  coverage-gate exit codes Task 3 covers.
- [Source: packages/sym/tests/test_classification_registry.py] — the DB-free fake-source + monkeypatch
  conventions to mirror.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Amelia / bmad-dev-story)

### Debug Log References

- `uv run pytest tests/test_classification_yahoo_profile.py tests/test_classification_registry.py` → 59 passed (Task 1)
- `uv run pytest tests/test_classification_sec_sic.py tests/test_classification_registry.py` → 55 passed (Task 2)
- `uv run pytest tests/test_cli.py` → 6 passed (Task 3)
- `uv run pytest tests/test_classification_report.py` → 6 passed (Task 4)
- `uv run pytest` → 753 passed, 0 failed (Task 5); `ruff check` clean on touched files

### Completion Notes List (2026-06-18)

**Task 1 — Yahoo circuit-breaker.** `MAX_CONSECUTIVE_ERRORS = 5` + `last_short_circuited` side-channel.
The breaker counts caught `YahooProfileError`s; ANY non-error outcome (a hit OR a clean no-profile)
resets the counter, so only a genuine consecutive run (the outage signature) trips it — scattered bad
names never do. On trip, every not-yet-attempted identity's symbol is recorded and the accumulated
`found` is returned (fill-only; the next nightly retries). `fetch` now iterates `enumerate(list(...))`
so the remainder can be sliced. Design choice: the no-ticker / unmappable-MIC pre-checks (which make no
network call) neither increment nor reset the counter — they can't be part of an outage signal.

**Task 2 — SEC dedup.** `HttpSecClient.company_ciks` now collects ALL CIKs per ticker. Single-CIK (the
overwhelming majority) is unchanged with zero extra calls. A >1-CIK collision (ticker reassignment)
calls `_resolve_active_cik`: prefer the filer whose `submissions` still lists the ticker, tie-broken by
the most-recent `filingDate`; deterministic fallback to the first candidate when no submissions are
reachable. The collision is recorded on `HttpSecClient.last_ambiguous_ticker` and copied into
`SecSicGicsSource.last_ambiguous_ticker` via `getattr` (so a test fake without the attribute still works)
for `_render_sec` to report. The extra `submissions` fetches are bounded to colliding tickers only.

**Task 3 — CLI loop test.** DB-free: stubs `connect` (nullcontext), `load_dotenv`, `run_classification_chain`,
and `read_active_coverage`. Covers all five report branches on the correct stream (success/empty/skip →
stdout, FAILED → stderr) and the three coverage-gate exits (≥threshold→0, <threshold→2, `psycopg.Error`
on the coverage read→0 with writes-already-committed messaging).

**Task 4 — Golden report test.** New `test_classification_report.py` pins the exact line list of all five
`_render_*` closures via `SimpleNamespace` fakes (ctor-free). Includes the circuit-breaker line, its
absence when not tripped, and the ambiguous-ticker line. The empty-scope "— not queried" wording is pinned
exactly in the Task 3 CLI test.

**No regressions / no new dependency.** Stdlib `urllib` only; happy-path behaviour preserved by construction
(verified by the unchanged sec/yahoo/registry tests + the no-circuit-breaker golden). FMP non-US
symbol-format spot-check left out of scope (blocked on a live `FMP_API_KEY`) per the story.

### File List

- `packages/sym/src/sym/classification/yahoo_profile.py` (UPDATE) — `MAX_CONSECUTIVE_ERRORS` constant,
  `last_short_circuited` side-channel, consecutive-error circuit-breaker in `fetch`.
- `packages/sym/src/sym/classification/sec_sic.py` (UPDATE) — `company_ciks` all-CIK collection +
  `_resolve_active_cik`, `last_ambiguous_ticker` on `HttpSecClient` + `SecSicGicsSource`.
- `packages/sym/src/sym/classification/registry.py` (UPDATE) — `_render_yahoo` circuit-breaker line +
  `_render_sec` ambiguous-ticker line; import `MAX_CONSECUTIVE_ERRORS`.
- `packages/sym/tests/test_classification_yahoo_profile.py` (UPDATE) — 3 circuit-breaker tests.
- `packages/sym/tests/test_classification_sec_sic.py` (UPDATE) — 4 dedup/ambiguity tests + `HttpSecClient` import.
- `packages/sym/tests/test_cli.py` (UPDATE) — 3 `_cmd_classify` loop/coverage-gate tests + helpers.
- `packages/sym/tests/test_classification_report.py` (NEW) — 6 per-pass renderer golden tests.

### Review Findings (code review 2026-06-18, 3-layer adversarial: Blind / Edge / Acceptance)

decision-needed: none. Acceptance Auditor confirmed AC1–AC6 + the FMP out-of-scope constraint all met.

patch (all applied 2026-06-18):
- [x] [Review][Patch] MED — `_resolve_active_cik` could crash the WHOLE sec_sic pass on a malformed
  submissions payload (Blind + Edge, independently). `max(str(d) for d in dates if d)` raised `ValueError`
  when `filingDate` was a non-empty list of only-falsy values (`["", None]`); a `tickers` value that was a
  truthy non-iterable (int) raised `TypeError`. Neither was caught by `except SecSicError`, so it escaped
  `_resolve_active_cik` → `company_ciks` → `run_fill_pass`'s broad handler and aborted the entire fill —
  breaking the per-name isolation invariant. **FIXED:** guard `tickers` with `isinstance(.., (list, tuple))`
  (a bare string no longer char-iterates either) and build `valid_dates` before `max` (empty → `""`). Test:
  `test_resolve_active_cik_survives_malformed_submissions_without_raising`. [sec_sic.py `_resolve_active_cik`]
- [x] [Review][Patch] LOW — `_render_yahoo` read `src.last_short_circuited` directly while `_render_sec`
  used a defensive `getattr` — inconsistent, latent `AttributeError` for a source/fake lacking the attr.
  **FIXED:** `_render_yahoo` now reads via `getattr(src, "last_short_circuited", [])`. [registry.py]
- [x] [Review][Patch] LOW (test gap) — the date-only tie-break in `_resolve_active_cik` was untested (the
  dup-ticker test passed even if `filingDate` were ignored, since the active filer also listed the ticker).
  **FIXED:** added `test_company_ciks_duplicate_ticker_tie_breaks_on_recency_when_both_list_ticker` (both
  filers currently list the ticker → recency must break the tie). [tests/test_classification_sec_sic.py]

dismissed (5): lexical `filingDate` `max` — SEC EDGAR `filingDate` is contractually ISO `YYYY-MM-DD`, so
lexical == chronological, and the P1 guard makes it junk-safe; double-fetch of the resolved CIK's submissions
— bounded to rare collisions + throttled, caching would couple `company_ciks` to SIC resolution for negligible
gain; breaker counter "sees through" interspersed no-ticker/unmappable-MIC skips — intended outage semantics
(skips are not attempts); `last_short_circuited` count conflation/possible dupes — reporting-only, no data
impact; same-recency tie → directory order — intended deterministic fallback, ambiguity is surfaced via
`last_ambiguous_ticker`.

### Change Log

- 2026-06-18: Implemented classification-robustness (Tasks 1-5). Yahoo consecutive-failure circuit-breaker
  (AC 1,2), SEC duplicate-ticker/CIK active-filer resolution + ambiguity surfacing (AC 3), `_cmd_classify`
  loop-integration test (AC 4), per-pass report golden test (AC 5). 18 new tests; 753 pass, ruff clean.
  FMP non-US spot-check kept out of scope (no key). Status → review.
- 2026-06-18: Applied 3-layer code-review patches (1 Med malformed-payload crash guard in `_resolve_active_cik`,
  1 Low renderer getattr consistency, 1 Low date-tie-break test gap). +2 tests; 755 pass, ruff clean. No
  decision-needed, no deferrals. Status → done.
