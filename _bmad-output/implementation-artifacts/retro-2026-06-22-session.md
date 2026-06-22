# Retrospective — 2026-06-22 session arc (board close-out + 2 new stories)

**Date:** 2026-06-22
**Project Lead:** Andre
**Format:** owner-operated working retrospective (analysis + decisions + actions) — not a multi-person
ceremony, consistent with the QH retros. Scope is a **session arc**, not a single epic.

## What the session delivered (7 commits, `fff9218`→`1d036d8`)

| Thread | Outcome | Commit |
|--------|---------|--------|
| Monitor arc code-review | 4 stories (WEI board, WEI backdate, FX matrix, live cockpit) reviewed via 3 adversarial layers × 3 groups → 4 patches → all `done` | `fff9218` |
| QL-1 lineage finish-off | Verified AC10/12/13 were delivered downstream (QL-2/QL-3) + 22 lineage tests → `done` (status-housekeeping) | `df6f148` |
| nasdaq100 finish-off | Re-verified live (102 members, validate 10/3/1, lone FAIL pre-existing) → `done` | `a3f66fa` |
| Full data refresh | `sym eod` overall OK (15.1M `fact_returns`), macro 321,835 obs, altdata 1,378 obs | (data only) |
| non-brazil-gics-surgical-close | Reframed the gap (already 99.1%); FB spurious-ETF member reversed out of sp500 + new `manual` operator-asserted classification source closes 3 FTSE trusts → `done` | `4e65031` |
| indexes-add-vix | VIX on the Indexes page (create→dev→review→browser-verify); `category` field keeps it off the equity WEI board; honest level-not-return framing → `done` | `0b8ac0f`, `963c389`, `1d036d8` |

**Delivery:** board fully cleared (0 in-progress / 0 review remaining); 2 new stories end-to-end. 0
production incidents (dev environment). sym 840 / api 158 / web 132 tests green at close.

## What went well

- **Re-measuring live state before scoping reframed two "big" tasks into small ones.** The
  "non-Brazil GICS 134-row gap" was stale — `sec_sic`+`yahoo`+`wikidata` (shipped 2026-06-17) had
  already taken it to 99.1%; the live residual was **4 names** (1 data bug + 3 funds), not a mapping
  build. QL-1's "remaining AC10/12/13" were likewise already delivered by QL-2/QL-3. Both closed
  surgically instead of being re-built.
- **Adversarial code-review earned its keep on every story.** Monitor arc: 4 patches incl. a High
  test-masking (`getAllByText` satisfied by the grid alone) and an FX duplicate-React-key bug. VIX:
  the honesty-note's "figures below" didn't cover the "Since start" stat sitting above it + a
  required-vs-"(default)" Pydantic mismatch. None were caught by the dev pass.
- **The honesty discipline kept surfacing concrete fixes** — WEI "(market holiday)" tooltip asserting
  a cause it couldn't know; VIX framed as a level (no CAGR) not a return; the `manual` source tagged
  truthfully rather than mislabelled. The project's no-fabrication value did real work.
- **Membership corrections stayed reversible + audited** — FB (and the earlier PCLN/nasdaq100 cases)
  fixed via `reverse_change` tombstones, never destructive edits.
- **Browser verification closed the loop on VIX** — a real headless-Chrome/CDP drive (click the list
  button, read the DOM, screenshot) + an equity positive-control probe, despite no puppeteer/playwright.

## What didn't — patterns

- **The "silent recompute" stall scare.** `sym eod` looked hung — 29 minutes with no stdout, frozen
  output file — but it was the `recompute` step writing 15.1M `fact_returns` rows entirely DB-side
  (no per-row output). Diagnosed only by checking `pg_stat_activity` + the per-figi cursor. **Lesson:
  judge a long EOD step by the DB (cursor / active query / `fact_returns` recency), not stdout.**
- **Recurring spurious index members (PCLN/FB class).** A recycled ticker (`FB@XNYS`) resolved to a
  ProShares ETF and sat in S&P 500 — the same shape as PCLN (nasdaq100/sp500). It surfaces only as a
  GICS-completeness fail or a name-pattern sweep; there's no automated guard yet.
- **Env-blocked classification sources are invisible until probed.** Yahoo `quoteSummary` is
  404-blocked in the sim env, so the 3 FTSE trusts couldn't be classified automatically — only a
  direct source-probe revealed it (the EOD `classify` just reported "fills touched 0").
- **No committed browser-verification tooling.** Each verification re-improvised (dump-dom, then a
  hand-written CDP driver). The driver is now committed under `_bmad-output/verification/` but isn't a
  reusable skill yet.

## Decisions (Andre, 2026-06-22)

- **Non-Brazil GICS = surgical close**, not a SIC→GICS build (it already existed) and not the broader
  recurring-guard option. The 3 FTSE trusts closed via a new high-trust `manual` source; FB reversed.
- **VIX scope** = Indexes page only, kept off the equity WEI board via a data-driven `category` field,
  framed honestly as a level. The dedicated volatility tile + VIX term-structure cousins were declined
  (open questions left in the story).
- **Verify artifacts committed** to `_bmad-output/verification/indexes-add-vix/` (screenshot + CDP
  drivers + replay README).

## Action items / open ledger (not actioned — by decision)

- **Spurious-member guard (PCLN/FB class):** a `validate` check that flags an ETF/fund mis-resolved as
  an index constituent — offered during the GICS story, Andre chose the surgical close. Candidate if it
  recurs (it's now happened 3×: PCLN×2, FB).
- **Promote the CDP verify driver → a `verifier-*` skill** — the repo lacks browser-verification
  tooling; the committed `cdp_verify.mjs` is the seed.
- **Recompute progress heartbeat** — a periodic "N/M securities" line (or a run-log progress field)
  would have pre-empted the stall scare. Small, optional.
- **Standing ledger carried forward:** the 9 Monitor-arc deferrals (`deferred-work.md`), the VIX open
  questions (volatility tile, VIX9D/3M/VVIX/VSTOXX), and the full ECB FX backfill (operational).

## Readiness

- **Tests/build:** sym 840 + api 158 + web 132 green; ruff/tsc/eslint clean.
- **Data:** EOD + macro + altdata all refreshed this session.
- **Validate:** the only `overall: FAIL` is the pre-existing global `unpriced_securities` (delisted
  non-members) — untouched by this session's work, out of scope.
- **Deployment:** dev environment; nothing deployed. Live quotes remain env-blocked (sim); the manual
  browser pass is the standing pre-deploy step.
- **Significant discoveries:** none forcing a plan change. The recurring spurious-member and
  stale-ledger patterns are process notes, not roadmap changes.

## Decision summary

A clean close-out session: the open board went to zero, two new stories shipped end-to-end with
adversarial review + (for VIX) real-browser verification, and the long-standing non-Brazil-GICS thread
is finally closed. The durable lessons are **re-measure before scoping** (two stale "big" tasks were
mostly done) and **judge long DB steps by the database, not stdout**. No new epic pending.
