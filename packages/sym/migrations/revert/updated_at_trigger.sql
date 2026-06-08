-- Revert sym:updated_at_trigger from pg

BEGIN;

DROP FUNCTION IF EXISTS set_updated_at();

COMMIT;
