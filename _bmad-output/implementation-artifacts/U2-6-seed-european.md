# Story U2.6: Seed European flagship index universes (current)

Status: review

## Story

As Andre,
I want the European flagship indexes registered and seeded current,
so that I can track them now and build their point-in-time history forward honestly.

## Acceptance Criteria

1. Seeding DAX, FTSE 100, CAC 40, EURO STOXX 50, IBEX 35, FTSE MIB, AEX, SMI captures current membership with `pit_valid_from = today` (build-forward).
2. Non-US listings resolve against the existing exchanges/calendars (ISIN-first resolver + MIC mappings).
3. A pre-`pit_valid_from` query on a European universe is refused/flagged; verified live for at least DAX + CAC 40.

## Tasks / Subtasks

- [x] Task 1: European index specs in the Wikipedia source (title + MIC + `yahoo_suffix`) for DAX/CAC40/FTSE100/IBEX35/FTSEMIB/AEX/SMI/EUROSTOXX50 (AC #1)
- [x] Task 2: Yahoo-suffix → MIC mapping (`split_yahoo_suffix`) so each member resolves to its true home venue (critical for pan-European EURO STOXX 50) (AC #2)
- [x] Task 3: register + live-populate the 8 universes (current snapshot → pit=today) (AC #1, #2)
- [x] Task 4: DB-free tests (suffix mapping, per-venue routing) + live pre-pit refusal verification (AC #3)

## Dev Notes

- European Wikipedia tables carry Yahoo-suffixed tickers (`ADS.DE`, `AIR.PA`, `NESN.SW`) whose suffix encodes the listing exchange. `split_yahoo_suffix` maps the suffix → operating MIC and strips to the base ticker, so OpenFIGI resolves each name on its real venue (a share-class dot like `BT.A` is left intact). This makes pan-European indexes resolve correctly without a single forced MIC.
- Current-snapshot universes have no usable changes table, so members join `poll_bounded` at today and `pit_valid_from = today` (build-forward) — a pre-pit query is refused (no false history), exactly the honesty boundary.
- All target MICs (XETR/XPAR/XLON/XMAD/XMIL/XAMS/XSWX/XBRU/XHEL/…) are present in the exchange reference table with OpenFIGI exch_codes, so resolution works against existing data.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `wikipedia.py`: `SUFFIX_MIC` + `split_yahoo_suffix`; `yahoo_suffix` spec flag threaded through `_constituent_changes`; 8 European built-in specs.
- **Live-populated (verified):** dax 40/40, cac40 40/40, ftse100 92/100, ibex35 35/35, ftsemib 40/40, aex 25/25, smi 19/20, estoxx50 49/50 — all `pit_valid_from = 2026-06-07` (build-forward). EURO STOXX 50's 50 names resolved across 7 venues (XBRU/XAMS/XETR/XPAR/XMAD/XMIL/XHEL) via suffix routing. Unresolved names retained-and-flagged (survivorship).
- Pre-pit refusal verified live (DAX query at 2020-01-01 → `PitBoundaryError`).
- 4 new DB-free tests (12 in the Wikipedia suite); ruff clean.

### File List
- `src/sym/universe/providers/wikipedia.py` (modified — suffix mapping + European specs)
- `tests/test_universe_wikipedia.py` (modified — suffix + per-venue tests)
- `_bmad-output/implementation-artifacts/U2-6-seed-european.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U2.6: European flagship seeding via Wikipedia + Yahoo-suffix→MIC routing. Live-populated 8 indexes (~340 names, build-forward pit). 12 Wikipedia tests. Completes Epic U2. |
