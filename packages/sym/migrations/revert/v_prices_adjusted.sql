-- Revert sym:v_prices_adjusted from pg

BEGIN;

DROP VIEW IF EXISTS v_prices_adjusted;
DROP AGGREGATE IF EXISTS product(numeric);

COMMIT;
