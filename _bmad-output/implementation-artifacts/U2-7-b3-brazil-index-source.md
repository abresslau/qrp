# Story U2.7: B3 (Brazil) index source — IBOV + IBrX

Status: review (source built; population pending)

## Story

As the operator, I want Brazilian index universes (Ibovespa, IBrX) sourced from the
**official B3 exchange** portfolio, with a defined maintenance plan, so I can add and
keep current the headline Brazil indexes without a scraped/proxy source.

## Acceptance Criteria

1. A `b3` index-source archetype that fetches B3's official `GetPortfolioDay` portfolio.
2. Index keys `ibov` (B3 code `IBOV`) and `ibx` (`IBXX` = IBrX-100) → constituents on `BVMF`.
3. Snapshot semantics: membership = the constituent ticker **set** at `end`, emitted as
   `poll_bounded` JOINs; an empty/garbled parse is a loud `IndexSourceError` (never "all left").
4. Plugs into the existing `IndexProvider` source-preference (`--source-pref b3`) + the
   maintenance machinery — no bespoke upkeep.
5. DB-free + network-free tests (fake client); a read-only live smoke confirms the wiring.

## Maintenance plan (required before population — see memory rule)

- **Source of truth:** B3 `GetPortfolioDay` (authoritative; no corroboration needed).
- **Mechanism:** snapshot → `sym universe monitor <id>` re-fetches + diffs vs projected
  membership → appends JOIN/LEAVE events. Idempotent.
- **Cadence:** daily via the `sym eod` monitor step (auto-covers all `kind='index'`); real
  churn lands at B3's **3×/year** rebalance (Jan/May/Sep) + ad-hoc corporate events.
- **Gating/review:** two-stage gate + accuracy gate; large swaps held for `sym universe review`.
- **PIT honesty:** `pit_valid_from` = first monitor date (build-forward; the endpoint has no
  history). Leavers tracked forward; survivorship-safe.

## Tasks / Subtasks

- [x] `ARCHETYPE_B3` added to the archetype registry.
- [x] `providers/b3.py`: `_portfolio_token` (base64 query), `parse_portfolio_tokens` (pure),
      `HttpB3Client`, `B3IndexSource` + `_B3_SPECS` (ibov→IBOV, ibx→IBXX), self-registers.
- [x] `index_provider.py` imports `b3` for self-registration.
- [x] `tests/test_b3.py` — 7 DB-free tests (archetype registered, parse, fetch JOINs,
      ibx→IBXX, unknown-key + empty-parse errors, token round-trip).
- [ ] **Population (pending, operational):** `sym universe add ibov|ibx --kind index --index
      <key> --source-pref b3` → `refresh` → OpenFIGI resolve (BVMF, exch_code `BZ`) → backfill
      (yfinance `.SA`) → recompute. Brazil plumbing already exists (exchange BVMF, BVMF calendar
      snapshot, Yahoo `.SA` suffix).

## Dev Notes

- B3 encodes its query as base64 JSON in the URL path (`GetPortfolioDay/{b64}`).
- Reuses BVMF infra that was already seeded (exchange row exch_code `BZ`, 14.6k-session BVMF
  calendar, `YAHOO_SUFFIX['BVMF']='.SA'`), so no new region plumbing or migration.
- `ibx` defaults to **IBrX-100** (`IBXX`, ~99 names); IBrX-50 (`IBXL`) is a one-line spec change.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- B3 source archetype built + registered; live read-only smoke: IBOV=78, IBX=99 constituents,
  tokens `ticker:<COD>@BVMF`, provenance `b3:IBOV`/`b3:IBXX`. 7 DB-free tests; ruff clean.
- Brazil was out of the original US+Europe scope; this extends it. Population deferred per
  the operator's "build source first, then populate" sequencing.

### File List
- `src/sym/universe/providers/b3.py` (new)
- `src/sym/universe/providers/index_source.py` (ARCHETYPE_B3)
- `src/sym/universe/providers/index_provider.py` (self-register import)
- `tests/test_b3.py` (new)
- `_bmad-output/implementation-artifacts/U2-7-b3-brazil-index-source.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-08 | Story U2.7: B3 (Brazil) index source archetype + ibov/ibx specs; live-verified (78/99). Population pending. |
