-- Revert sym:fx_rate_review from pg

BEGIN;

DROP TABLE IF EXISTS fx_rate_review;

COMMIT;
