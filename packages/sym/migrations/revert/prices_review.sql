-- Revert sym:prices_review from pg

BEGIN;

DROP TABLE IF EXISTS prices_review;

COMMIT;
