-- Deploy sym:fundamentals_column_order to pg
-- requires: fundamentals_market_cap_lcy

BEGIN;

-- Postgres can't reorder columns in place; market_cap_usd was appended last (after the audit
-- columns). Rebuild with a clean order -- market_cap_usd next to market_cap_lcy -- preserving
-- all data + constraints + the index + the updated_at trigger. (No incoming FKs / dependent
-- views, verified before the rebuild.) Index/constraint names are schema-global, so we stage
-- the data in a temp table and DROP the original first, freeing the `fundamentals_pk` name.
CREATE TEMP TABLE _fundamentals_copy ON COMMIT DROP AS SELECT * FROM fundamentals;

DROP TABLE fundamentals;

CREATE TABLE fundamentals (
    composite_figi      CHAR(12)    NOT NULL,
    as_of_date          DATE        NOT NULL,
    market_cap_lcy      NUMERIC,
    market_cap_usd      NUMERIC,
    shares_outstanding  NUMERIC,
    currency_code       CHAR(3),
    source              TEXT        NOT NULL,
    detail              JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fundamentals_pk PRIMARY KEY (composite_figi, as_of_date),
    CONSTRAINT fundamentals_figi_fk FOREIGN KEY (composite_figi)
        REFERENCES securities (composite_figi),
    CONSTRAINT fundamentals_nonneg_chk CHECK (
        (market_cap_lcy IS NULL OR market_cap_lcy >= 0)
        AND (shares_outstanding IS NULL OR shares_outstanding >= 0)
    )
);

INSERT INTO fundamentals
    (composite_figi, as_of_date, market_cap_lcy, market_cap_usd, shares_outstanding,
     currency_code, source, detail, created_at, updated_at)
SELECT composite_figi, as_of_date, market_cap_lcy, market_cap_usd, shares_outstanding,
       currency_code, source, detail, created_at, updated_at
  FROM _fundamentals_copy;

CREATE INDEX idx_fundamentals_as_of_date_mktcap
    ON fundamentals (as_of_date, market_cap_lcy DESC NULLS LAST);

CREATE TRIGGER fundamentals_set_updated_at
    BEFORE UPDATE ON fundamentals FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE fundamentals IS 'Minimal fundamentals input (Story U5.1): market cap + shares outstanding, effective-dated, for rules-based screens (U5.2). Missing values stay NULL + flagged, never faked.';
COMMENT ON COLUMN fundamentals.market_cap_lcy IS 'Market cap in the local (native) currency = close_raw x shares_outstanding at as_of_date. Pairs with market_cap_usd.';
COMMENT ON COLUMN fundamentals.market_cap_usd IS 'market_cap restated to USD at the as_of_date FX (USD-base resolver, <=date within the outage cap). Derived snapshot; recompute via recompute_market_cap_usd; NULL if no FX covers the currency/date.';

COMMIT;
