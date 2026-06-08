# Story B4: MSCI index-level file importer

Status: review

## Story

As Andre,
I want to import MSCI index level series from a downloaded MSCI export,
so that benchmarks with no Yahoo symbol (MSCI World NTR, ACWI, EAFE, …) get level data under the same sym_id identity.

## Acceptance Criteria

1. Parse an MSCI export (CSV/Excel): skip the metadata preamble to the `Date` header, take date + the index-value column, tolerate thousands separators and several date formats, skip footer notes.
2. Resolve the index by its `msci` xref (or create the instrument on first import with name + currency); upsert levels into `index_levels` (immutable, source='msci').
3. CLI `sym msci-import <path> --msci-code <code> [--name --currency]`; recompute index returns after import.
4. DB-free parser tests + live import verification.

## Tasks / Subtasks

- [x] Task 1: pure `parse_msci_rows` (preamble/footer-tolerant; ISO + "Mmm DD, YYYY" + etc.; comma strip; non-positive/blank skip)
- [x] Task 2: `read_rows` (CSV via utf-8-sig; Excel via pandas) + `load_msci_file` (resolve/create sym_id by msci xref; immutable upsert)
- [x] Task 3: CLI `sym msci-import` (+ index-returns recompute)
- [x] Task 4: DB-free parser tests + live import verification

## Dev Notes

- No new schema — reuses `instrument` (msci xref) + `index_levels`. MSCI files are per-index; the operator downloads from MSCI's EOD index-data search and runs `sym msci-import`. The parser is tolerant of MSCI's varying export shapes.
- Live-verified with a synthetic MSCI World file (sym_id resolved via the `msci=990100` xref, levels written, returns recomputed); synthetic rows were cleaned up, so MSCI World remains **identity-only** until a real MSCI download is imported.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `benchmarks/msci.py`: pure `parse_msci_rows`, `read_rows` (csv/excel), `load_msci_file` (resolve-or-create by msci xref, immutable level upsert).
- `cli.py`: `sym msci-import <path> --msci-code [--name --currency]` + post-import index-returns recompute.
- **Live-verified:** imported a synthetic MSCI World file → resolved sym_id 2059 via the `msci=990100` xref, 3 levels written, returns recomputed; synthetic rows cleaned up.
- 4 DB-free parser tests; full suite **327 pass**, ruff clean.

### File List
- `src/sym/benchmarks/msci.py` (new)
- `src/sym/cli.py` (modified — `msci-import` command)
- `tests/test_msci_import.py` (new)
- `_bmad-output/implementation-artifacts/B4-msci-file-import.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story B4: MSCI index-level file importer (tolerant CSV/Excel parser + sym_id-resolving loader + `sym msci-import` CLI). Live-verified. 4 DB-free tests. |
