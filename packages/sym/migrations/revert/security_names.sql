-- Revert sym:security_names from pg

BEGIN;

DROP TABLE IF EXISTS security_names;

COMMIT;
