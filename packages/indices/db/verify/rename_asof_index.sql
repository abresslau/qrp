-- Verify indices:rename_asof_index on pg
-- The canonical-named index exists; the retired `asof` name is gone.

BEGIN;

DO $$
BEGIN
    IF to_regclass('indices.idx_fact_index_returns_as_of_date') IS NULL THEN
        RAISE EXCEPTION 'idx_fact_index_returns_as_of_date is missing';
    END IF;
    IF to_regclass('indices.idx_fact_index_returns_asof') IS NOT NULL THEN
        RAISE EXCEPTION 'retired idx_fact_index_returns_asof still present';
    END IF;
END $$;

COMMIT;
