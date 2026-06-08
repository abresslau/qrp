-- Revert sym:fx_source_rank from pg

BEGIN;

DROP FUNCTION IF EXISTS fx_source_rank(TEXT);

COMMIT;
