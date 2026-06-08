-- Revert sym:universe_membership from pg

BEGIN;

DROP TABLE IF EXISTS universe_membership;

COMMIT;
