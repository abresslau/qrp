-- Verify equity:rename_asof_constraint on pg
-- The canonical-named constraint exists; the retired `asof` name is gone.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'equity.fact_returns'::regclass
           AND conname = 'fact_returns_as_of_date_not_null'
    ) THEN
        RAISE EXCEPTION 'fact_returns_as_of_date_not_null is missing';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'equity.fact_returns'::regclass
           AND conname = 'fact_returns_asof_not_null'
    ) THEN
        RAISE EXCEPTION 'retired fact_returns_asof_not_null still present';
    END IF;
END $$;

COMMIT;
