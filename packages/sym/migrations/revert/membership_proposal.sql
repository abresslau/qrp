-- Revert sym:membership_proposal from pg

BEGIN;

DROP TABLE IF EXISTS membership_proposal;

COMMIT;
