-- Revert sym:fundamentals_effective_date from pg

BEGIN;

ALTER INDEX idx_fundamentals_effdate_mktcap RENAME TO idx_fundamentals_asof_mktcap;
ALTER TABLE fundamentals RENAME COLUMN effective_date TO as_of;

COMMIT;
