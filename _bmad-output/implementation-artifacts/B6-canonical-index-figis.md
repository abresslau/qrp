# Story B6: Canonical index FIGIs (static map)

Status: review

## Story
As the operator, I want canonical OpenFIGI ids attached to index instruments where they
can be pinned unambiguously, so an index shares one id with other systems — without
sacrificing reconstructability.

## Acceptance Criteria
1. FIGIs live in a committed static map (`INDEX_FIGIS: yahoo_symbol -> figi`), NOT a live scrape.
2. A deterministic seeder attaches them via `instrument_xref(source='figi')`, idempotent.
3. `sym benchmarks` attaches on every run; `sym benchmarks --attach-figis` is a standalone re-attach.
4. Coverage is partial-by-design (only cleanly-pinned entries); extending = add a line + re-run.
5. DB-free tests + live verification.

## Dev Notes
- The unkeyed OpenFIGI **search** endpoint is rate-limited (429 storms) and noisy (~100 look-alikes
  per name; SPX/UKX canonicals sit beyond page 1), so it cannot reliably auto-curate all 18. FIGI is
  an *optional* xref (sym_id + yahoo/msci is the spine), so a verified static map is the right artifact.
- Verified by exact-ticker match (`<TICKER> Index`, securityType2='Index'): DAX BBG000HY4HW9,
  AEX BBG000KHVFM7, CAC 40 BBG000HY2S75, IBEX 35 BBG000JD3ZR0.
- Not pinned via unkeyed search (need keyed account / manual): S&P family, FTSE 100, Nikkei 225,
  Dow, SMI, EURO STOXX 50, FTSE MIB, Nasdaq, Russell 2000, IBOVESPA, MSCI World.

## Dev Agent Record
### Completion Notes List
- `benchmarks/figis.py`: `INDEX_FIGIS` static map + `attach_index_figis` seeder.
- CLI: `--attach-figis` flag; full `benchmarks` run also attaches.
- Live: 4 attached, 0 missing; verified in instrument_xref. 2 DB-free tests.
### File List
- `src/sym/benchmarks/figis.py` (new); `src/sym/cli.py` (--attach-figis); `tests/test_index_figis.py` (new)
- `_bmad-output/implementation-artifacts/B6-canonical-index-figis.md` (new)
### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Story B6: committed canonical index FIGI map + deterministic seeder; 4 verified FIGIs attached live. |
