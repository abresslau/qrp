-- Deploy sym:prices_review_sweep_flag to pg
-- requires: prices_review

-- The weekly sweep (AR-10) records source-side retroactive corrections as a
-- reviewable flag on the existing price row, rather than overwriting it. Extend
-- the flag_type domain to allow 'sweep_divergence'.
BEGIN;

ALTER TABLE prices_review DROP CONSTRAINT prices_review_flag_type_chk;
ALTER TABLE prices_review ADD CONSTRAINT prices_review_flag_type_chk
    CHECK (flag_type IN ('price_jump', 'price_on_non_trading_day', 'sweep_divergence'));

COMMENT ON COLUMN prices_review.flag_type IS 'price_jump (>±50% split-adjusted single-day move) | price_on_non_trading_day | sweep_divergence (re-fetch differs from stored raw).';

COMMIT;
