-- Revert indices:rename_asof_index from pg
-- Restore the original index name.

ALTER INDEX IF EXISTS indices.idx_fact_index_returns_as_of_date
    RENAME TO idx_fact_index_returns_asof;
