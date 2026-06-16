# Epic QH — Production Hardening — Retrospective

**Date:** 2026-06-15
**Facilitator:** Amelia (Developer) · **Project Lead:** Andre
**Participants:** Amelia (Developer), Winston (Architect), John (PM), Murat (QA)

## Epic summary

Cross-cutting production-hardening epic. The caveats that separate the v1 spikes from
production, plus the DB-per-package migration follow-ups.

| Story | Outcome |
|-------|---------|
| QH.1 — Close the Brazil GICS gap | done (2026-06-11) — B3 taxonomy → GICS; ibov/ibx GICS FAILs 43+49→0; non-Brazil gaps (134 rows) ledgered |
| QH.2 — Live quote source (live-PnL) | **deploy-gated** — engine ready; no live quote source reachable in-env; unblocks at deploy |
| QH.3 — Read-only DB role for sym reads | done (2026-06-14) — `qrp_readonly` physically refuses writes; dual-credential model realised; one post-merge correction caught by live smoke |
| QH.4 — Operate live progress via SSE | done (2026-06-15) — `/api/operate/jobs/stream`; reuses `list()` verbatim; review fixed a connection-lifetime leak window |
| QH.5 — Migration finish-off | done (2026-06-11) — `deploy_all` + topology gate + DuckDB spike; first run caught 12 rotten verify scripts |
| QH.6 — Generic module framework + command palette (FR-2) | done (2026-06-15) — `SUBNAV_PROVIDERS` registry (NFR-10) + ⌘K palette; review fixed AC5 result-surfacing + an empty-submenu refetch loop |

**Delivery:** 5/6 stories done; QH.2 deploy-gated (not incomplete — operator decision). 0 production
incidents. Every story shipped with tests/build green and a faithful `deferred-work.md` entry.
Epic QH is functionally complete; the FR map (FR-13…FR-22) is fully closed. No epic beyond QH exists.

## What went well

- **Scope discipline (NFR-10 just-in-time).** QH.6 deliberately did NOT build a speculative
  bundle-loader — the backend toggle-mounting (AR-Q3) and Next's file-routing already covered it,
  so the real work was the subnav registry + palette. QH.4 was the same instinct: transport-only,
  reuse `DbOperateGateway.list()` verbatim, no new contract.
- **Physical guarantees over conventions.** QH.3's `qrp_readonly` role makes sym reads
  write-incapable by Postgres, proven by a live-gated test — not "read-only by convention."
- **Verification caught what implementation missed — every time.** QH.5's `deploy_all` found 12
  rotten verify scripts invisible since the renames; QH.3's live smoke caught the gateway reader
  breaking the whole Q2 See surface; the adversarial code reviews on QH.4 and QH.6 each found
  genuine bugs (the connection-lifetime leak window; the AC5 result-swallowing).
- **Ledger discipline.** The `deferred-work.md` ledger served as durable memory; every caveat was
  captured with enough context to act on later.

## What didn't — patterns

- **No console test infrastructure (systemic, thrice-ledgered).** QH.6 was the largest frontend
  change in the project and was verified with `tsc` + `eslint` + `next build` + manual only. The
  registry fail-safe state machine and the palette keyboard/filter logic are exactly what unit
  tests should guard. → Action #1.
- **RED lint baseline.** 12 pre-existing `react-hooks/set-state-in-effect` errors that console
  work routes around rather than fixes. → Action #2.
- **Dev drifted from its own spec (QH.6 AC5).** The story's Task 2 said "reuse the O.4 envelope for
  the POST /run response"; the implementation fire-and-forgot it. All three review layers flagged
  it. The spec was right — the build drifted. → Action #5 (a self-check gate).
- **Environment as a hard constraint.** QH.2 is genuinely blocked: no live quote source is
  reachable in the simulated-2026 env (FRED + live quotes blocked by policy). Recorded as
  deploy-gated, not incomplete.

## Continuity

No prior epic retrospective exists (QH is cross-cutting; the Q-epics closed without formal retros).
The `deferred-work.md` ledger has been the de-facto continuity mechanism and held across the epic.

## Action items

1. **[Headline] Console test harness** — stand up `vitest` + `@testing-library/react` in
   `apps/web`; backfill tests for the QH.6 command palette (substring filter, ↑/↓ selection,
   read-only-launch vs writer-route, result/`msg` surfacing) and the subnav-provider registry
   fail-safe. Owner: Dev. Success: `npm test` green in `apps/web` with palette + registry covered.
2. **Clear the RED lint baseline** — fix the 12 `set-state-in-effect` errors (derive-don't-sync)
   so console work starts green. Owner: Dev. Pairs with #1.
3. **Palette a11y pass** — focus trap + focus restoration on close + body scroll-lock +
   selected-item `scrollIntoView` (deferred in the QH.6 review). Owner: Dev.
4. **Non-Brazil GICS** — SEC SIC→GICS fallback to close the 134 remaining GICS FAIL rows
   (ftse100 69, US 34, others), per the QH.1 lead. Owner: Dev. Success: `sym validate` GICS FAILs → 0.
5. **Process: spec-reuse self-check** — in `dev-story`, when a Task names a specific pattern to
   reuse (e.g. an error envelope), treat it as an AC checkbox in the dev self-check, so the
   QH.6-AC5-class miss is caught before review. Owner: Process.
6. **Broad introspection-scoped read-only role** (low priority) — make the gateway serving-path and
   the offline `lineage` generator's sym reads physically write-incapable too (QH.3 deferred item).
   Owner: Dev.

## Readiness assessment

- **Tests/build:** all green — operate 22/22, api 56/56 (incl. topology gate), console `tsc` +
  `eslint` (touched files) + `next build` (18/18 routes).
- **Production incidents:** 0.
- **Open verification:** the manual live-console pass for QH.4 (SSE in the Network tab) and QH.6
  (⌘K palette end-to-end) is the one un-run check — needs servers up; it is the operator step both
  stories flagged. Not a blocker for the epic; a pre-deploy checklist item.
- **Deployment:** dev environment; nothing deployed.
- **Significant discoveries:** none that force a plan change (no next epic; FRs complete). The
  console-test gap is the main systemic finding, now Action #1.

## Decisions (Andre)

- **QH.2 is deploy-gated, not incomplete.** Engine ready; unblocks when a real-time quote source
  exists at deploy. Epic QH counts functionally complete.
- **Headline action = console test harness** (Action #1).
