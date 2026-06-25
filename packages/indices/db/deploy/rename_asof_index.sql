-- Deploy indices:rename_asof_index to pg
-- requires: indices_schema

-- The fact_index_returns as_of_date index was named `idx_fact_index_returns_asof` (carried verbatim
-- from the original sym DDL — the lone `asof` holdout; the column + the fact_index_extremes index use
-- the canonical `as_of_date`). Rename it to match. Catalog-only rename, no rebuild. IF EXISTS so a
-- fresh deploy that somehow already has the canonical name is a no-op.

ALTER INDEX IF EXISTS indices.idx_fact_index_returns_asof
    RENAME TO idx_fact_index_returns_as_of_date;
