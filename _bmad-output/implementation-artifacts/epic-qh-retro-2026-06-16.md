# Epic QH — Production Hardening — Retrospective (augment)

**Date:** 2026-06-16
**Project Lead:** Andre
**Supersedes nothing — augments:** [epic-qh-retro-2026-06-15.md](epic-qh-retro-2026-06-15.md) (held while QH.2 was still deploy-gated).

> Owner-operated project — this is a working retrospective (analysis + decisions + actions),
> not a multi-person ceremony.

## Why a second QH retro

The 2026-06-15 retro recorded **QH.2 as "deploy-gated — no live quote source reachable in-env"**
and Epic QH as 5/6 done. **That premise was superseded the same day:** a re-probe found the Yahoo
**v8 chart** endpoint (`query1.finance.yahoo.com/v8/finance/chart/{sym}`) reachable without auth
(the v7 `/finance/quote` endpoint 401s — needs a crumb). So QH.2 was actually **built, adversarially
reviewed, patched, and merged on 2026-06-16** — Epic QH is now genuinely **6/6 complete**.

| Story | Outcome (updated) |
|-------|-------------------|
| QH.1 — Close the Brazil GICS gap | done (2026-06-11) — non-Brazil 134-row gap still ledgered (Action #4 below) |
| QH.2 — Live quote source (live-PnL) | **done (2026-06-16)** — `GET /api/sym/quotes` (Yahoo v8 chart, stdlib, not persisted) + live portfolio PnL reusing the EOD weight×return engine; reviewed + 2 honesty-bug patches; merged `889141a` |
| QH.3 — Read-only DB role for sym reads | done (2026-06-14) |
| QH.4 — Operate live progress via SSE | done (2026-06-15) |
| QH.5 — Migration finish-off | done (2026-06-11) |
| QH.6 — Generic module framework + command palette | done (2026-06-15) |

**Delivery:** 6/6 done. 0 production incidents across the epic. FR-13…FR-22 fully closed.

## What went well (new — QH.2)

- **Re-probing unblocked the epic.** "No live quote source in-env" was too broad — it was really
  "the endpoints we first tried were blocked." The v8 chart path works (US ~real-time, `.SA`/B3
  ~15 min delayed); `regularMarketTime` gives an honest per-symbol as-of stamp. The
  `reference-env-external-sources` memory was corrected.
- **"Swap the price source" turned out exact.** The live return is computed from the payload's own
  `previousClose` (`live_price / previousClose − 1`) — so no sym price read, no widening of the
  `qrp_readonly` surface, and a clean reuse of the existing weight×return dot-product
  (`portfolios.gateway.returns` / `analytics.gateway._portfolio_daily`).
- **Honest degradation was the real new design surface.** `/api/sym/quotes` is the first
  `/api/sym/*` endpoint to fetch externally at serve time; the DB-read endpoints never needed it.
  Two-tier degradation landed cleanly: per-symbol miss → `unavailable` row (`price:null`),
  whole-source outage → 503 envelope (`{error:{type:"unavailable",…}}`, produced by the app-wide
  handler).
- **Topology discipline held via deliberate duplication.** The `YAHOO_SUFFIX` map + fetcher were
  replicated across `qrp_api.modules.sym.quotes` and `analytics.quotes` rather than importing
  `packages/sym` (the no-sym-imports gate) — the project's duplicate-until-a-third-consumer posture,
  ledgered.
- **The adversarial review earned its keep a third time** (after QH.4, QH.6). Notably **both real
  bugs were honesty bugs — the exact thing QH.2 exists to get right:**
  1. the portfolio freshness rollup could paint a delayed/timeless quote with the green **live**
     badge (a priced constituent with no `regularMarketTime` never tripped `any_delayed`);
  2. a malformed-numeric Yahoo payload escaped the parse guard → 500 instead of degrading to a
     per-symbol `unavailable`.
  Both were "the spec was right, the build drifted on an edge" — same shape as QH.6's AC5 miss.

## What didn't — patterns (continuity)

- **Console test harness (prior Action #1) — still not done, now 4× implicated.** QH.2's live-PnL
  badge is *more* untested frontend logic, again verified by `tsc` + `eslint` + manual only.
  → **Promoted to a story: QH.7** (Andre's call, 2026-06-16).
- **RED lint baseline (prior Action #2) — still red.** QH.2 didn't add to the `analytics-panel`
  `set-state-in-effect` baseline but didn't clear it. Pairs with QH.7.
- **Triage must verify the loud finding.** The Auditor's most prominent flag (the 503-envelope
  shape) was a **false positive** — the global `http_exception_envelope` in `main.py` already
  produces it (`_error_type_for(503)=="unavailable"`, tested). Triage held only because we grep'd
  the handler + its test rather than trusting the finding's prominence.

## Prior action-item follow-through (from 2026-06-15)

| # | Action | Status |
|---|--------|--------|
| 1 | Console test harness (`vitest` + `@testing-library`) | ❌ not done → **promoted to QH.7** |
| 2 | Clear the RED lint baseline (12 `set-state-in-effect`) | ❌ not done (folds into QH.7) |
| 3 | Palette a11y pass (focus trap/restore/scroll-lock) | ❌ not done (still ledgered) |
| 4 | Non-Brazil GICS (SEC SIC→GICS, 134 rows) | ❌ not done (still ledgered) |
| 5 | Process: spec-reuse self-check in `dev-story` | ⏳ partial — the QH.2 review caught edge drift, but no formal dev self-check gate yet |
| 6 | Broad introspection-scoped read-only role | ❌ not done (low priority, ledgered) |

## New action items

7. **[Promoted to story] QH.7 — Console test harness.** Stand up `vitest` + `@testing-library/react`
   in `apps/web`; backfill tests for the ⌘K palette, the subnav-provider registry fail-safe, and the
   QH.2 live-PnL badge (freshness → style mapping, `n_priced` gating). Fold in clearing the RED lint
   baseline (prior #2). Owner: Dev. Success: `npm test` green in `apps/web`, lint baseline clean.
8. **Process — name the probe + a re-test trigger for every environment "block."** An env-block
   finding (e.g. "live quotes unreachable") must record the **exact endpoint/probe tested** and a
   **re-test trigger**, so a "blocked" fact can't ossify the way QH.2's deploy-gating did on a
   premise a single re-probe overturned. Capture in `reference-env-external-sources`. Owner: Process.

## QH.2-specific deferrals (logged to deferred-work.md, code review 2026-06-16)

Future-dated/clock-skewed quote always reads "live"; Yahoo symbol not URL-encoded; duplicate FIGIs
double-fetch; no max-size cap on the HTTP read; no shared parity test across the two fetcher twins.
Plus the pre-existing QH.2 ledger (ThreadPool fan-out, in-memory TTL cache, SSE/streaming quotes,
intraday persistence, live heatmap, multi-provider fallback).

## Readiness assessment

- **Tests/build:** services/api 78/78 green (incl. `test_topology_discipline.py`); ruff/tsc clean.
- **QH.2 live e2e:** run this session (env DB + Yahoo both up) — quotes endpoint returned correct
  symbols/prices/currencies + honest `delayed` labels; live-PnL on a real portfolio priced + labelled;
  missing portfolio → 404; empty figis → 422.
- **Production incidents:** 0.
- **Deployment:** dev environment; nothing deployed. The one open caveat is unchanged — the manual
  *console* pass (the live badge in a browser) is the operator pre-deploy step, not a blocker.
- **Significant discoveries:** none forcing a plan change. With QH.7 spun up, the console test gap
  moves from a perennial ledger note to an actionable story.

## Decisions (Andre, 2026-06-16)

- **Keep the "name the probe + re-test trigger" lesson as a standing process item** (Action #8).
- **Promote the console test harness to a real story (QH.7).** Epic QH reopened to hold it.
