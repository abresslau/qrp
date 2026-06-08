-- Revert sym:fundamentals_column_order from pg
-- Rebuild with the prior column order (market_cap_usd appended last, after the audit columns).

BEGIN;

CREATE TEMP TABLE _fundamentals_copy ON COMMIT DROP AS SELECT * FROM fundamentals;

DROP TABLE fundamentals;

CREATE TABLE fundamentals (
    composite_figi      CHAR(12)    NOT NULL,
    as_of_date          DATE        NOT NULL,
    market_cap_lcy      NUMERIC,
    shares_outstanding  NUMERIC,
    currency_code       CHAR(3),
    source              TEXT        NOT NULL,
    detail              JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_cap_usd      NUMERIC,
    CONSTRAINT fundamentals_pk PRIMARY KEY (composite_figi, as_of_date),
    CONSTRAINT fundamentals_figi_fk FOREIGN KEY (composite_figi)
        REFERENCES securities (composite_figi),
    CONSTRAINT fundamentals_nonneg_chk CHECK (
        (market_cap_lcy IS NULL OR market_cap_lcy >= 0)
        AND (shares_outstanding IS NULL OR shares_outstanding >= 0)
    )
);

INSERT INTO fundamentals
    (composite_figi, as_of_date, market_cap_lcy, shares_outstanding, currency_code,
     source, detail, created_at, updated_at, market_cap_usd)
SELECT composite_figi, as_of_date, market_cap_lcy, shares_outstanding, currency_code,
       source, detail, created_at, updated_at, market_cap_usd
  FROM _fundamentals_copy;

CREATE INDEX idx_fundamentals_as_of_date_mktcap
    ON fundamentals (as_of_date, market_cap_lcy DESC NULLS LAST);

CREATE TRIGGER fundamentals_set_updated_at
    BEFORE UPDATE ON fundamentals FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
