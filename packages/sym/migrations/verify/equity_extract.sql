-- Verify sym:equity_extract on pg
-- The equity objects must be GONE from the sym database (they live in the equity database now).

BEGIN;

DO $$
DECLARE
    rel text;
BEGIN
    FOREACH rel IN ARRAY ARRAY[
        'prices_raw', 'corporate_actions', 'price_gaps', 'prices_review',
        'pipeline_backfill_progress', 'pipeline_run_log', 'fact_returns',
        'fact_price_extremes', 'v_prices_adjusted'
    ] LOOP
        IF to_regclass('public.' || rel) IS NOT NULL THEN
            RAISE EXCEPTION '% still present in the sym database', rel;
        END IF;
    END LOOP;
    -- the index facts MUST remain (kept in sym)
    IF to_regclass('public.fact_index_returns') IS NULL THEN
        RAISE EXCEPTION 'fact_index_returns was dropped — index facts must stay in sym';
    END IF;
    IF to_regclass('public.return_window') IS NULL THEN
        RAISE EXCEPTION 'return_window was dropped — it is kept in sym for the index facts';
    END IF;
END $$;

ROLLBACK;
