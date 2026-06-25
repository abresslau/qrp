-- Verify indices:indices_schema on pg
-- Every index object lives in the `indices` schema.

BEGIN;

DO $$
DECLARE
    rel text;
BEGIN
    FOREACH rel IN ARRAY ARRAY[
        'return_window', 'index_levels', 'fact_index_returns',
        'fact_index_extremes', 'universe_benchmark'
    ] LOOP
        IF to_regclass('indices.' || rel) IS NULL THEN
            RAISE EXCEPTION '% is not in the indices schema', rel;
        END IF;
    END LOOP;
END $$;

COMMIT;
