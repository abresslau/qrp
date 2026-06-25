-- Verify equity:equity_namespace on pg
-- Every equity object must live in the `equity` schema (not public).

BEGIN;

DO $$
DECLARE
    rel text;
BEGIN
    FOREACH rel IN ARRAY ARRAY[
        'prices_raw', 'corporate_actions', 'price_gaps', 'prices_review',
        'pipeline_backfill_progress', 'pipeline_run_log', 'fact_returns',
        'fact_price_extremes', 'currency', 'return_window', 'v_prices_adjusted'
    ] LOOP
        IF to_regclass('equity.' || rel) IS NULL THEN
            RAISE EXCEPTION '%  is not in the equity schema', rel;
        END IF;
        IF to_regclass('public.' || rel) IS NOT NULL THEN
            RAISE EXCEPTION '% still present in public', rel;
        END IF;
    END LOOP;
END $$;

COMMIT;
