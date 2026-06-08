-- Verify sym:prices_raw_drop_retrieved_at on pg

BEGIN;

-- The column is gone.
SELECT 1 / (CASE WHEN NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'prices_raw' AND column_name = 'retrieved_at'
) THEN 1 ELSE 0 END);

ROLLBACK;
