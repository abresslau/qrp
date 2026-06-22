-- Revert sym:exchange_bbg_exchange_code from pg

BEGIN;

ALTER TABLE exchange DROP COLUMN bbg_exchange_code;

COMMIT;
