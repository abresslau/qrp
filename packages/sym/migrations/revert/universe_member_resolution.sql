-- Revert sym:universe_member_resolution from pg

BEGIN;

DROP TABLE IF EXISTS universe_member_resolution;

COMMIT;
