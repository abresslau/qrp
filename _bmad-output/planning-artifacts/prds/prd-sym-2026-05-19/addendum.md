# sym PRD — Addendum

## A-1. Broader Data Warehouse Vision

sym is Module 1 of a larger quantitative investment data warehouse. The full architecture as envisioned:

```
sym (security master + market data)   ← FIGI is the universal join key
universe (investable universe definitions, criteria-based)
alternative data (alt data sources)
research (LLM-generated analysis and reports)
─────────────────────────────────────────────
portfolio construction (L/S trade signals)
```

**Ultimate goal:** Long/Short equity portfolios generated from AI-driven research built on top of clean, FIGI-anchored data. sym is the foundation everything else joins back to.

Each module is a separate database. Universe, alt data, and research PRDs are future work.

---

## A-2. FactSet Methodology Reference

Research conducted 2026-05-19 via FactSet Enterprise SDK documentation.

**Return type (dividend_adjust parameter):**
- `PRICE` (default): price change only, no dividends
- `EXDATE_C`: compound total return, dividends reinvested on ex-date — this is the sym standard for TR
- `EXDATE`: simple return, dividends accumulated on ex-date, not reinvested
- `PAYDATE_C`: compound total return, dividends reinvested on pay date

**Window anchor logic:**
- WTD/MTD/QTD/YTD: prior period-end close (calendar anchors)
- 1M–1Y: rolling (same calendar date N months/years back)
- 2Y–30Y + IPO: annualized compound CAGR (not cumulative)
- IPO window uses first available closing price, not offer price

**Note:** FactSet field names use "PCT" suffix without explicit TR/PR qualifier — return type is set at request time, not field level. The CSV sample shared (`Untitled 34_2026-05-19-2046.csv`) likely reflects price return (FactSet default) unless EXDATE_C was explicitly set. Total return validation (PRD §7 SM-3) therefore requires a separately pulled FactSet TR reference with `dividend_adjust=EXDATE_C` explicitly specified.

---

## A-3. Database Technology Decision

**Chosen:** PostgreSQL.

**Rejected:** DuckDB + Parquet.

**Rationale:** Total data volume estimated at ~5–10 GB (10k securities × 10Y × 252 days, prices + return matrix). DuckDB provides meaningful advantage at hundreds of GB to TB. At this scale, PostgreSQL is simpler to operate, natively supported by DBeaver, directly usable for future REST API, and the standard paradigm for a relational security master. DuckDB remains relevant if the warehouse expands to ingest high-frequency alt data or large text corpora.

---

## A-4. Data Source Limitations (yfinance → EODHD Migration)

**yfinance (dev phase):**
- Rate limiting: ~950 tickers per session; bulk 10k downloads require retry/session management
- Corporate action accuracy: documented silent errors, especially non-US
- Yahoo ToS: prohibits automated commercial access
- Survivorship bias: delisted names not reliably available

**EODHD (production target, ~$20/month EOD All World plan):**
- 150k+ tickers, 60+ exchanges
- Adjusted prices, splits, dividends globally
- More reliable international coverage
- Still not survivorship-bias-free

**Migration trigger:** EODHD migration is targeted at the point of production use at a firm, before research outputs are relied upon for investment decisions (Yahoo ToS prohibits commercial automated access).
