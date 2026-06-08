-- Revert sym:instrument from pg

BEGIN;

DROP TABLE IF EXISTS instrument_xref;
DROP TABLE IF EXISTS instrument;

COMMIT;
