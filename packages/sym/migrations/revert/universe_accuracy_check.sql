-- Revert sym:universe_accuracy_check from pg

BEGIN;

DROP TABLE IF EXISTS universe_accuracy_check;

COMMIT;
