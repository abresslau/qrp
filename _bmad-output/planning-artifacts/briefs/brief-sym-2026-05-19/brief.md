---
title: "sym — Global Equity Security Master"
status: final
created: 2026-05-19
updated: 2026-05-20
---

# sym — Global Equity Security Master

## Executive Summary

sym is an internal equity security master and market data store for a quantitative investment research practice. It anchors every security to a permanent OpenFIGI identifier that survives ticker changes, SEDOL reassignments, and vendor transitions — making it a long-lived infrastructure asset rather than a data-vendor dependency. The universe covers US equities and developed markets, approximately 4,000–8,000 investable names, with 10 years of daily adjusted prices, returns, market cap, and volume. sym is the foundational data layer for the Quant Research Tool — a factor-model and backtesting platform under development — providing the canonical record for instrument identity and market data. sym is built for the author's own quantitative research today; design choices preserve the option to productize and license sym to other independent practices later (see Vision).

## Who This Serves

**Primary user: the quant researcher.** Needs a reliable, queryable universe of securities with clean historical price data to run factor models, backtests, and portfolio analysis. Current pain: data identity and quality problems — ticker-keyed data breaks when companies rename or relist, corporate action adjustments are inconsistently applied across ad hoc sources, and there is no single canonical record for instrument identity. Each research project re-solves the same plumbing problems. Success means running cross-sectional analysis on the full investable universe without first resolving data quality issues.

**Secondary consumer: the Quant Research Tool.** sym's schema and query interface become the contract the research platform depends on. Stability of the identity layer is what makes the downstream tool's results reproducible over time.

## The Problem

Commercial solutions that solve this well — FactSet, S&P Capital IQ, Bloomberg — are enterprise-priced and impractical for an early-stage or independent quant practice. The alternative — stitching together ad hoc sources — reproduces the same problems at lower cost but higher maintenance burden.

The cost accumulates. A security master built on unstable identifiers accrues technical debt that becomes expensive to unwind once downstream tools depend on it. The earlier the identity layer is established correctly, the less it costs.

## The Solution

**Identity first.** Every security is mapped to a CompositeFIGI via the OpenFIGI API — a free, open standard that does not change with ticker or SEDOL changes. All other identifiers (ticker, SEDOL, CUSIP, ISIN, exchange code) are attributes of the security, not its identity. The FIGI is the permanent key.

**Data layer.** Daily EOD market data — adjusted close, open, high, low, volume, market cap, and daily return — is stored against the permanent FIGI key. 10 years of history at launch, updated daily in a batch pipeline. Each security carries reference metadata: company name, exchange, country, currency, and GICS sector/industry classification.

**Vendor independence by design.** The data pipeline is abstracted from any single source. yfinance is the initial provider for development; EODHD (~$20/month) is the identified migration target for any commercial use. Bloomberg, FactSet, or buyer-supplied vendors are viable future sources. Because the FIGI identifier is open and vendor-neutral, migrating the data source requires only an ETL update — the security master structure, downstream integrations, and historical records are unaffected. If sym is ever distributed to other practices, the same abstraction lets each buyer plug in their own licensed feed without touching the identity layer.

**Architecture.** Python ETL pipeline. DuckDB + Parquet as the local-first storage layer, suited to the analytical query patterns of quantitative research (batch writes, heavy cross-sectional reads). Designed to migrate to PostgreSQL when the Quant Research Tool requires a server-based backend.

## Universe and Scope

**In scope — v1:**
- US equities (NYSE, NASDAQ, NYSE Arca)
- Developed market equities (major exchanges: LSE, Euronext, Deutsche Börse, TSX, ASX, Tokyo, and others)
- Investable universe: ~4,000–8,000 securities filtered by liquidity and market cap (criteria defined at implementation)
- 10 years of daily EOD history; daily batch updates thereafter

**Out of scope — v1:**
- Intraday or real-time data
- Fundamental / financial statement data
- Options, futures, fixed income, ETFs, crypto
- Emerging markets (including Brazil) — deferred to v1.x
- Survivorship-bias-free historical universe (known data source limitation)

## Known Risks and Constraints

**Data sourcing — primary risk.** yfinance has documented rate limiting (~950 tickers per session), inconsistent corporate action handling, and Yahoo ToS that prohibits commercial automated access. These are accepted for the author's personal research use only. Migration to EODHD or an equivalent licensed source is a hard precondition for any commercial activity — including distribution of sym to third parties, paid analysis derived from sym, or production use at a firm. yfinance must not be the active data source past that gate.

**Survivorship bias.** The investable universe reflects currently listed securities. Historical analysis has survivorship bias for periods where delistings are not captured. Accepted limitation of free-source data.

**GICS licensing.** Production-grade GICS classifications require an MSCI/S&P license. The development phase will use GICS-approximated classifications from open sources (financedatabase).

## Success Criteria

- All securities in the universe have a stable CompositeFIGI as the primary key
- Adjusted price series pass a sanity check: no single-day returns exceeding ±50% without an identified corporate action
- Daily update pipeline runs unattended and surfaces data quality anomalies automatically
- The Quant Research Tool can query cross-sectional return data for the full universe without data identity resolution overhead

## Vision

sym becomes the permanent identity and market data foundation for an independent quantitative research capability. When a commercial data license is acquired — Bloomberg, FactSet, or otherwise — sym is the integration target: the FIGI mapping ensures vendor data drops cleanly into an existing structure rather than requiring a rebuild. The investment in the identity architecture pays forward indefinitely. As the practice grows, sym adds markets and richer data fields; the identity layer remains the stable spine throughout.

Beyond the author's own research, sym is designed with the option of being productized and sold to other independent quant practices later. The commercial path is not the v1 target, but design choices that make sym credible to a future buyer — schema stability as a public contract, vendor-pluggable data sourcing, and classification choices that survive licensing constraints — are made now rather than retrofitted. This is design optionality, not a commitment to ship.
