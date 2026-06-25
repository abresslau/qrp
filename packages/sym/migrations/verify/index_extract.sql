-- Verify sym:index_extract on pg
-- The index objects must be GONE from the sym database (they live in the indices database now);
-- return_window + the instrument identity spine must REMAIN.

BEGIN;

DO $$
DECLARE
    rel text;
BEGIN
    FOREACH rel IN ARRAY ARRAY[
        'index_levels', 'fact_index_returns', 'fact_index_extremes', 'universe_benchmark'
    ] LOOP
        IF to_regclass('public.' || rel) IS NOT NULL THEN
            RAISE EXCEPTION '% still present in the sym database', rel;
        END IF;
    END LOOP;
    IF to_regclass('public.return_window') IS NULL THEN
        RAISE EXCEPTION 'return_window was dropped — it is kept in sym';
    END IF;
    IF to_regclass('public.instrument') IS NULL THEN
        RAISE EXCEPTION 'instrument was dropped — the identity spine stays in sym';
    END IF;
END $$;

ROLLBACK;
