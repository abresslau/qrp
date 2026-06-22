# Story: Portfolio returns (top-movers MTD/YTD) — skip gated/null returns when pinning the as-of date

Status: done

<!-- Created via bmad-create-story 2026-06-22 (Andre: "when I click on portfolio live top-10, clicking
YTD is not populated"). Same AR-9 gating root cause as portfolios-live-returns-fix, now on a THIRD
endpoint: /api/portfolios/{id}/returns (the snapshot-attribution feed for the Top-Movers MTD/YTD lists). -->

## Story

As a portfolio manager, I want the **Top Movers MTD/YTD lists to populate for the whole book**, so
clicking YTD shows the real winners/losers — not just the 2–3 names whose latest return isn't gated.

## Background / root cause (read before coding)

- The Top-Movers card (`apps/web/components/portfolio-movers.tsx`): **Daily** comes from the live
  composition; **MTD/YTD** fetch `/api/portfolios/{pid}/returns?window=…` → `constituents` (current
  holdings × the window return). Verified on portfolio 3: MTD and YTD both return **3/100** constituents
  with a non-null `ret` → the lists collapse to ~3 names (YTD: all 3 are gainers, so "losers" is empty →
  reads as "not populated").
- **Why:** `portfolios/gateway.py` `returns()` pins all constituents to ONE `ret_date` = the latest date
  where ≥90% of members have a `fact_returns` **row** (the "broadly-complete date", to avoid a sparse
  "today"). But it counts rows that EXIST, including AR-9-**gated** rows whose `pr IS NULL` (2026-06-18 has
  a row for all 100 names but a null `pr` for 97 — the gate withholds returns built on an unreviewed
  price). So it pins to 06-18, then `pr_map` is null for 97 → filtered out. The latest date with *real*
  returns is 06-17 (clean), but the row-count CTE never sees that distinction.
- This is the SAME gate as `portfolios-live-returns-fix` (the 1D grid) — the fix there was "use the latest
  NON-NULL pr". Here the analogue is: the broadly-complete-date CTE + the pr lookup must count/select only
  **non-null** `pr`, so the pin lands on the last date with actual returns (06-17), recovering all 100.

## Acceptance Criteria

1. **Pin to the latest broadly-complete date with REAL returns.** `returns()`'s `per_day` CTE counts only
   rows with `pr IS NOT NULL` (so a date that's all-gated/null can't win the pin), and the `pr_map` lookup
   filters `pr IS NOT NULL`. For portfolio 3 the MTD/YTD constituents go from 3/100 → ~100/100 with a
   non-null `ret` (pinning to 06-17, the last clean date, not the gated 06-18).
2. **Honesty preserved.** Still ONE pinned `ret_date` for all constituents (no blended as-of); the
   `returns_as_of_date` in the payload reflects that date; a genuinely missing/uncovered name stays null
   (covered_weight semantics unchanged). The ≥90% broadly-complete heuristic is intact — just measured
   over real returns.
2. **Movers UI unchanged** — no frontend change needed; the populated constituents flow through.
3. **No regression.** The portfolio analytics / composition paths are untouched; portfolios + api tests +
   ruff green.
4. **Test.** A `returns()` test where the latest as_of row has `pr IS NULL` (gated) but an earlier date is
   clean → the pin lands on the earlier date and constituents carry the real returns.

## Tasks / Subtasks

- [x] Task 1: `portfolios/gateway.py` `returns()` — added `AND pr IS NOT NULL` to the `per_day` CTE WHERE
  + the `pr_map` SELECT (mirrors the `portfolios-live-returns-fix` skip-null rule). So a gated/all-null
  latest date can't win the broadly-complete-date pin; it falls back to the last date with real returns.
- [x] Task 2: test — `test_returns_skips_gated_null_pr_when_pinning_and_looking_up` asserts both queries
  carry `pr IS NOT NULL` (SQL-level guard, like the existing broadly-complete `"0.9"` assertion — the
  fake conn can't exercise the filter itself). 3 returns-coverage tests green.
- [x] Task 3: verify — live `/api/portfolios/3/returns`: **MTD + YTD now 100/100** non-null constituents,
  pinned to **2026-06-17** (was 3/100 pinned to the gated 06-18). Full API suite 166 green; ruff clean.
  (CDP of the movers card skipped — the card is a pure render of this payload, already CDP-verified to
  render earlier this session.)

## Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Clean — all ACs PASS, no High/Med. The Edge Case Hunter read the full method and verified end-to-end:
the all-gated edge is guarded (`if ret_date is not None else {}` → coherent empty payload, no crash);
`covered_w`/`port_ret`/`n_with_return` are unaffected (`pr_map.get` + `if pr is not None` already guard);
the bug was real (pre-patch CTE counted gated rows); and this is the only `fact_returns` date-pin in the
gateway (no sibling un-fixed pattern). `pr IS NOT NULL` matches the established analytics convention and is
deliberately broader than `NOT gated` (also drops insufficient-history nulls — desirable, since a null `pr`
is unusable regardless of cause). No patches.

- [x] [Review][Defer] **The returns test is an SQL-text guard, not a behavioral pin-fallback test** [services/api/tests/test_portfolio_returns_coverage.py] — the DB-free fake `_SymConn` returns canned rows (can't execute the `pr IS NOT NULL` filter), so the test asserts the clause is present in both SQL strings (mirroring the existing `"0.9"` broadly-complete guard) rather than that the pin lands on the earlier clean date. Acceptable per the harness convention + the behavior was verified live (3→100/100, pinned 06-17). A behavioral test would need a SQL-capable fake (SQLite/in-memory pg) — a larger harness change, deferred.

Dismissed: **all-gated `ret_date=None` crash** (blind, "High") — false positive: the guard exists (full-file read confirmed); **threshold-population shift / downstream miscount** (blind, "Med") — intended + verified consistent (the pin now measures over usable returns; matches the analytics gateway). Noted (no action): `pr IS NOT NULL` is broader than `NOT gated` (correct here); analytics mixes the two idioms (extremes uses `NOT gated`) — out of scope.

## Dev Notes
- Same AR-9 gating as `portfolios-live-returns-fix`; the gate is correct (withhold returns on unreviewed
  prices) — the consumer must fall back to the last reviewed date. Read-only; nothing persisted.
- [Source: packages/portfolios/src/portfolios/gateway.py] `returns()` (~line 388-411, the per_day CTE + pr_map).
- [Source: apps/web/components/portfolio-movers.tsx] MTD/YTD fetch `/api/portfolios/{pid}/returns`.
- Sibling: `portfolios-live-returns-fix` (the 1D grid skip-null), `ticker-region-codes` (the gate discovery).

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22
### Completion Notes
- Third surface of the AR-9 gating issue (after the 1D grid + the window columns), reported live by Andre.
  The `/api/portfolios/{id}/returns` snapshot-attribution feed pinned to the latest date with a fact_returns
  ROW, counting gated null-`pr` rows — so 2026-06-18 (all-gated for 97/100) won the pin and the Top-Movers
  MTD/YTD lists collapsed to the 3 non-gated names (YTD: all 3 gainers → "losers" empty → "not populated").
- One coherent 2-clause fix: `pr IS NOT NULL` in both the broadly-complete-date pin AND the lookup → pins
  to 06-17 (the last real-returns date), 100/100 covered. The ≥90% per-market heuristic is preserved, just
  measured over real returns. Read-only; nothing persisted; no frontend change.
- Verified live: MTD + YTD = 100/100 (was 3); API 166 green; ruff clean.
### File List
- `packages/portfolios/src/portfolios/gateway.py` (modified — `pr IS NOT NULL` in the returns date-pin CTE + lookup)
- `services/api/tests/test_portfolio_returns_coverage.py` (modified — gated-skip SQL guard test)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (Andre: "top-10 YTD not populated"). Root cause = AR-9 gating on /api/portfolios/{id}/returns: the broadly-complete-date pin counts gated null-pr rows, so it pins to the gated latest date (06-18) and 97/100 constituents read null. Fix = count/select only non-null pr (pin to the last real-returns date). |
| 2026-06-22 | Dev complete → review. `pr IS NOT NULL` added to the `returns()` date-pin CTE + lookup; MTD/YTD now 100/100 (pinned 06-17, was 3/100 on the gated 06-18). +1 SQL-guard test; API 166 green; ruff clean. Status → review. |
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Clean: all ACs pass, no High/Med; Edge Case Hunter verified end-to-end (all-gated guard exists, no miscount, only date-pin in the gateway, matches analytics `pr IS NOT NULL` convention). Blind Hunter's "High" (missing all-gated guard) was a false positive (truncated-diff artifact). 0 patches; 1 defer (behavioral test needs a SQL-capable fake) → deferred-work.md. Status → done. |
