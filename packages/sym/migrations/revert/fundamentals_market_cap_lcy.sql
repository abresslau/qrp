-- Revert sym:fundamentals_market_cap_lcy from pg

BEGIN;

ALTER TABLE fundamentals RENAME COLUMN market_cap_lcy TO market_cap;

COMMIT;
