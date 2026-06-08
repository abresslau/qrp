-- Deploy sym:fundamentals_effective_date to pg
-- requires: fundamentals

BEGIN;

-- Rename fundamentals.as_of -> effective_date (Story U5.1 refinement). The column
-- is the date a fundamentals value takes effect (SCD-style, like
-- membership_event.effective_date), and the table is now a *historical series*
-- (one row per shares-outstanding observation per security), not a single
-- snapshot -- so the as_of name was misleading. Bare "date" is avoided (it shadows
-- the SQL type); effective_date matches the rest of the schema.
ALTER TABLE fundamentals RENAME COLUMN as_of TO effective_date;
ALTER INDEX idx_fundamentals_asof_mktcap RENAME TO idx_fundamentals_effdate_mktcap;

COMMENT ON COLUMN fundamentals.effective_date IS 'Date this fundamentals observation takes effect (historical series; SCD-style). A screen reads the latest observation on/before its evaluation date.';

COMMIT;
