-- Revert sym:gics_source_opinion from pg

BEGIN;

DROP TABLE IF EXISTS gics_source_opinion;

COMMIT;
