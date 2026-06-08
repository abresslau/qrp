-- Deploy sym:fundamentals_date_column to pg
-- requires: fundamentals_effective_date

BEGIN;

-- Rename fundamentals.effective_date -> date (operator preference). The column is
-- simply the date a fundamentals observation is for; "date" is the clearest name.
-- It is a non-reserved keyword in PostgreSQL, so it is a legal, unambiguous column
-- identifier (quoted here for explicitness).
ALTER TABLE fundamentals RENAME COLUMN effective_date TO "date";
ALTER INDEX idx_fundamentals_effdate_mktcap RENAME TO idx_fundamentals_date_mktcap;

COMMENT ON COLUMN fundamentals."date" IS 'Date this fundamentals observation is for (historical series; SCD-style). A screen reads the latest observation on/before its evaluation date.';

COMMIT;
