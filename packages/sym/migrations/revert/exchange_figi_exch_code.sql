-- Revert sym:exchange_figi_exch_code from pg

BEGIN;

ALTER TABLE exchange DROP COLUMN exch_code;

COMMIT;
