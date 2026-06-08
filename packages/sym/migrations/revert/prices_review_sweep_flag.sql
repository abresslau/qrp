-- Revert sym:prices_review_sweep_flag from pg

BEGIN;

ALTER TABLE prices_review DROP CONSTRAINT prices_review_flag_type_chk;
ALTER TABLE prices_review ADD CONSTRAINT prices_review_flag_type_chk
    CHECK (flag_type IN ('price_jump', 'price_on_non_trading_day'));

COMMIT;
