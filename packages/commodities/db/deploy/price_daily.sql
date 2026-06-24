-- Deploy commodities:price_daily to pg

BEGIN;

-- The `commodities` package's own database. v1 stores Tier-A vendor CONTINUOUS front-month series
-- per commodity (raw OHLCV + volume), stored verbatim; period changes / returns / vol are derived
-- on read. Two vintages in one row: `settle` (restated latest) + `first_settle` (immutable / PIT).
-- as_of_date = the trading date from the vendor, never the ingest date. Idempotent.
CREATE SCHEMA IF NOT EXISTS commodities;

CREATE TABLE IF NOT EXISTS commodities.price_daily (
    commodity_code     TEXT        NOT NULL,   -- canonical internal code (see commodities.universe)
    series_type        TEXT        NOT NULL DEFAULT 'continuous_front',
    as_of_date         DATE        NOT NULL,   -- trading date (canonical as_of_date)
    open               NUMERIC,
    high               NUMERIC,
    low                NUMERIC,
    settle             NUMERIC     NOT NULL,    -- daily settlement proxy (vendor close), restated
    volume             NUMERIC,
    first_settle       NUMERIC     NOT NULL,    -- first-published settle (immutable / PIT)
    source             TEXT        NOT NULL DEFAULT 'yfinance',
    first_published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_changed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- re-stamped when any OHLCV value changes
    CONSTRAINT price_daily_pk PRIMARY KEY (commodity_code, series_type, as_of_date),
    -- wide band (commodities are volatile; front-month WTI printed NEGATIVE in Apr-2020) — only
    -- bound gross corruption, never reject a real move.
    CONSTRAINT price_daily_settle_chk CHECK (settle > -1000 AND settle < 1000000),
    CONSTRAINT price_daily_first_chk  CHECK (first_settle > -1000 AND first_settle < 1000000)
);

CREATE INDEX IF NOT EXISTS idx_price_daily_code_date
    ON commodities.price_daily (commodity_code, series_type, as_of_date);
CREATE INDEX IF NOT EXISTS idx_price_daily_date
    ON commodities.price_daily (as_of_date);

COMMENT ON TABLE commodities.price_daily IS
    'Daily commodity prices — Tier-A vendor continuous front-month series, stored raw (immutable '
    'first_settle + restated settle). Derive period returns / vol / continuity on read.';

-- Stewardship queue: an implausible day-over-day move (when banding is enabled on load) lands here
-- instead of in price_daily. Never a silent bad print.
CREATE TABLE IF NOT EXISTS commodities.price_review (
    commodity_code TEXT        NOT NULL,
    series_type    TEXT        NOT NULL,
    as_of_date     DATE        NOT NULL,
    settle         NUMERIC     NOT NULL,
    prev_settle    NUMERIC,
    reason         TEXT        NOT NULL,
    source         TEXT        NOT NULL DEFAULT 'yfinance',
    flagged_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT price_review_pk PRIMARY KEY (commodity_code, series_type, as_of_date)
);

COMMIT;
