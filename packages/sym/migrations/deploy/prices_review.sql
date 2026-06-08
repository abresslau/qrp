-- Deploy sym:prices_review to pg
-- requires: price_storage

-- Stage-1 anomaly annotation (AR-9, NFR-1 annotate half). A suspect price still
-- lands in prices_raw; here it is FLAGGED for review, never discarded. The stage-2
-- gate (excluding unreviewed-flag rows from fact_returns) is Epic 3 -- which is why
-- each flag carries reviewed/resolution. One flag per (figi, date): idempotent
-- UPSERT on the PK. FK to prices_raw because a flag annotates a price that exists.
BEGIN;

CREATE TABLE prices_review (
    composite_figi  CHAR(12)    NOT NULL,
    session_date    DATE        NOT NULL,
    flag_type       TEXT        NOT NULL,
    detail          TEXT,
    pct_move        NUMERIC,
    source          TEXT        NOT NULL,
    reviewed        BOOLEAN     NOT NULL DEFAULT FALSE,
    resolution      TEXT,
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT prices_review_pk PRIMARY KEY (composite_figi, session_date),
    CONSTRAINT prices_review_flag_type_chk
        CHECK (flag_type IN ('price_jump', 'price_on_non_trading_day')),
    CONSTRAINT prices_review_resolution_chk
        CHECK (resolution IS NULL OR resolution IN ('confirmed', 'rejected')),
    -- reviewed iff a resolution has been recorded.
    CONSTRAINT prices_review_reviewed_chk CHECK (reviewed = (resolution IS NOT NULL)),
    CONSTRAINT prices_review_prices_fk
        FOREIGN KEY (composite_figi, session_date)
        REFERENCES prices_raw (composite_figi, session_date),
    CONSTRAINT prices_review_securities_fk
        FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi)
);

CREATE INDEX idx_prices_review_unreviewed
    ON prices_review (composite_figi) WHERE NOT reviewed;

CREATE TRIGGER prices_review_set_updated_at
    BEFORE UPDATE ON prices_review FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  prices_review            IS 'Stage-1 anomaly flags (AR-9/NFR-1). Suspect price still in prices_raw; gate at materialization is Epic 3.';
COMMENT ON COLUMN prices_review.flag_type  IS 'price_jump (>±50% split-adjusted single-day move) | price_on_non_trading_day.';
COMMENT ON COLUMN prices_review.pct_move   IS 'Split-adjusted single-day move for a price_jump flag; NULL otherwise.';
COMMENT ON COLUMN prices_review.reviewed   IS 'TRUE once a steward confirms/rejects; the Epic 3 gate excludes unreviewed-flag rows.';

COMMIT;
