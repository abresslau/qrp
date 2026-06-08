-- Revert sym:fundamentals_date_column from pg

BEGIN;

ALTER INDEX idx_fundamentals_date_mktcap RENAME TO idx_fundamentals_effdate_mktcap;
ALTER TABLE fundamentals RENAME COLUMN "date" TO effective_date;

COMMIT;
