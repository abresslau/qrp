# Story 2.2: Source-abstraction contract and yfinance adapter

Status: review

## Story

As an ingestion pipeline,
I want a single `fetch_ohlcv(figi, start, end) -> OhlcvResult` contract with a config-keyed adapter registry,
so that the source is swappable and all source-specific logic is isolated behind one boundary.

## Acceptance Criteria

1. **Given** the contract, **Then** `OhlcvResult` carries RAW prices + normalized `splits`/`dividends` (Decimal, ex-date keyed, currency explicit, missing = `[]` not null, stamped `source` + `retrieved_at`).
2. **Given** config, **When** a source key is set, **Then** the matching adapter is selected from a registry (not import-based); an adjusted-only source raises `UnsupportedSourceError`.
3. **Given** the HARD RULE, **Then** corporate-action factors derive ONLY from explicit action records — never reverse-engineered from adjusted/raw price ratios — enforced at the adapter boundary (AR-6).
4. **Given** the cross-vendor contract test, **When** two adapters cover the same name, **Then** derived cumulative factors match (split exact; dividend tolerance max(0.5%, $0.005); ex-date exact).

## Tasks / Subtasks

- [x] Task 1: contract types + errors in `src/sym/sources/contract.py` (AC: #1, #3)
  - [x] `OhlcvBar` (date + O/H/L/C `Decimal`, volume int), `SplitEvent` (ex_date, ratio), `DividendEvent` (ex_date, amount) — all `Decimal`, ex-date keyed
  - [x] `OhlcvResult` (figi, currency, bars, splits, dividends, source, retrieved_at); `__post_init__` enforces missing = `[]` not None; NO adjusted-close field
  - [x] `OhlcvSource` Protocol (`fetch_ohlcv(figi, start, end) -> OhlcvResult`); `SourceError`, `UnsupportedSourceError`, `UnknownSymbolError`
  - [x] `cumulative_split_factor(splits, asof)` — derived ONLY from explicit splits (HARD RULE); `actions_agree(a, b)` cross-vendor comparator (split exact, dividend tol); `assert_ohlcv_contract(result)` conformance check
- [x] Task 2: config-keyed registry in `src/sym/sources/registry.py` (AC: #2)
  - [x] `register_source(key, factory, *, adjusted_only=False)`, `get_source(key, **kwargs)`; unknown key → `UnknownSourceError`; `adjusted_only` → `UnsupportedSourceError`
  - [x] `sym.config.source_key()` reads `SYM_SOURCE` (default `yfinance`)
- [x] Task 3: yfinance adapter in `src/sym/sources/yfinance_adapter.py` (AC: #1, #3)
  - [x] `YFinanceSource.fetch_ohlcv` via an injectable history fn (`auto_adjust=False`); emit RAW O/H/L/C by **un-split-adjusting Yahoo's split-adjusted prices via the explicit splits** (HARD RULE), **discard `Adj Close`**, extract explicit `Dividends`/`Stock Splits` as Decimal ex-date events; stamp source + retrieved_at + currency
  - [x] self-registers under `yfinance` (not adjusted-only)
- [x] Task 4: tests in `tests/test_sources.py` (AC: #1–#4)
  - [x] `OhlcvResult` invariants (missing → []; Decimal); `assert_ohlcv_contract`
  - [x] registry: select yfinance; unknown key errors; adjusted-only → `UnsupportedSourceError`
  - [x] yfinance adapter over a fake history frame: un-split-adjusted to raw (not Adj Close), split + dividend extracted, ex-date keyed Decimal
  - [x] factor derivation (cumulative split factor); `actions_agree` (split exact, dividend within tol, ex-date exact)

## Dev Notes

- **Pattern:** same boundary discipline as `identity/figi.py` and `classification/gics.py` — the vendor dependency is injected (a `history` callable) so the adapter is unit-tested with a fake pandas frame, no network. Live fetch is the verification step.
- **HARD RULE (AR-6):** the adapter extracts factors only from yfinance's explicit `Dividends`/`Stock Splits` columns and **discards `Adj Close`**. There is no code path that derives a factor from a price ratio — the factor helpers take `splits`/`dividends`, never prices. (Architecture reconciliation FR-5/AR-7: store raw OHLCV + explicit factors; never a vendor adjusted close.)
- **yfinance shape:** `Ticker(sym).history(start, end, auto_adjust=False, actions=True)` → `Open/High/Low/Close/Volume/Dividends/Stock Splits` (+ `Adj Close`). `Stock Splits`/`Dividends` are 0 on non-event days; non-zero rows are the ex-date events. `Decimal(str(x))` to avoid float artifacts.
- **figi → vendor symbol** is injected (`symbol_for`); the DB-backed resolver (symbology → Yahoo symbol with exchange suffixes) is wired by the ingestion stories (2.3/2.5). NFR-8: yfinance is personal-research-only.
- **Cross-vendor (AC #4):** only yfinance exists now; EODHD is Story 2.7. This story delivers the comparator (`actions_agree`) + per-adapter conformance (`assert_ohlcv_contract`); the actual two-vendor diff is realized in 2.7 against committed EODHD fixtures.
- **Testing standard:** DB-free and network-free unit tests (fake history frame, injected clock for `retrieved_at`).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.2: Source-abstraction contract and yfinance adapter]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-5 — Source-abstraction contract]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-6 — HARD RULE (factor provenance)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- `uv run pytest` → 70 passed (13 new source tests); `uv run ruff check` clean.
- Live: fetched AAPL 2018–2024 via the real yfinance adapter.

### Completion Notes List

- Boundary discipline mirrors `figi.py`/`gics.py`: the vendor dependency (`history`) and figi→symbol mapping are injected; tests use a fake pandas frame + injected clock, no network.
- Registry is config-keyed (`SYM_SOURCE` → `get_source`), adapters self-register; an `adjusted_only` source raises `UnsupportedSourceError`. yfinance registered as raw+factors.
- **Live-found correctness fix (important):** yfinance's `auto_adjust=False` OHLCV is **split-adjusted at source** (AAPL 2018-01-02 came back as $43, not the ~$172 actually traded). Storing that as "raw" while also storing the explicit 4:1 split would make Epic 3 **double-adjust**. The adapter now un-split-adjusts back to true raw using the EXPLICIT split factors (`raw = yahoo * cumulative_split_factor`, `volume = yahoo / factor`) — HARD-RULE-compliant (factors from explicit records, not price ratios). Verified live: 2018-01-02 → $172.26 raw, volume 25.5M; `Adj Close` ignored; no adjusted-close field on the result.
- **AC #4 scope:** only yfinance exists now, so the cross-vendor comparator (`actions_agree`) + per-adapter conformance (`assert_ohlcv_contract`) ship here and are unit-tested; the actual two-vendor diff completes in Story 2.7 against committed EODHD fixtures.

### File List

- `src/sym/sources/contract.py` (new) — OhlcvResult/Bar/Split/Dividend, OhlcvSource protocol, errors, factor + comparison helpers, conformance check.
- `src/sym/sources/registry.py` (new) — config-keyed adapter registry + UnsupportedSourceError gate.
- `src/sym/sources/yfinance_adapter.py` (new) — YFinanceSource (un-split-adjusts to raw), self-registers.
- `src/sym/sources/__init__.py` (modified) — public exports + adapter registration side-effect.
- `src/sym/config.py` (modified) — `source_key()` (`SYM_SOURCE`, default yfinance).
- `tests/test_sources.py` (new) — 13 tests (DB-free, network-free).
- `_bmad-output/implementation-artifacts/2-2-source-abstraction.md` (new) — this story spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.2: source-abstraction contract (`OhlcvResult`/`fetch_ohlcv`), config-keyed registry, yfinance adapter, HARD-RULE factor helpers. Live fix: un-split-adjust yfinance's split-adjusted prices to true raw via explicit factors. 13 tests; verified live on AAPL. Status → review. |
