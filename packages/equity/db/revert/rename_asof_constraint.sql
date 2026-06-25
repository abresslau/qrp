-- Revert equity:rename_asof_constraint from pg
-- Restore the original constraint name.

BEGIN;

ALTER TABLE equity.fact_returns
    RENAME CONSTRAINT fact_returns_as_of_date_not_null TO fact_returns_asof_not_null;

COMMIT;
