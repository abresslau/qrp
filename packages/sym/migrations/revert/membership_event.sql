-- Revert sym:membership_event from pg

BEGIN;

DROP TABLE IF EXISTS membership_event;

COMMIT;
