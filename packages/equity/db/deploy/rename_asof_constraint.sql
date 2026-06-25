-- Deploy equity:rename_asof_constraint to pg
-- requires: equity_namespace

-- The fact_returns NOT NULL constraint was the lone holdout still using the retired `asof` token
-- (`fact_returns_asof_not_null`), carried over verbatim from the original sym schema. The column and
-- every index on it use the canonical `as_of_date`; rename the constraint to match. PG 18 stores a
-- named NOT NULL as a real pg_constraint row (contype='n'), so RENAME CONSTRAINT applies — a
-- catalog-only rename, no table rewrite, no data touched.

BEGIN;

ALTER TABLE equity.fact_returns
    RENAME CONSTRAINT fact_returns_asof_not_null TO fact_returns_as_of_date_not_null;

COMMIT;
