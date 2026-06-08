-- Revert sym:fundamentals_market_cap_usd from pg

BEGIN;

ALTER TABLE fundamentals DROP COLUMN IF EXISTS market_cap_usd;

COMMIT;
