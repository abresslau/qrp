-- Revert sym:securities_review_queue from pg

BEGIN;

DROP TABLE IF EXISTS securities_review_queue;

COMMIT;
