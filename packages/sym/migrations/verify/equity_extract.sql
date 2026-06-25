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
    -- return_window MUST remain (kept in sym — read by the sym API/portfolio/analytics; the indices
    -- DB has its own seeded copy). The index facts themselves moved on to the `indices` package in a
    -- later change (sym:index_extract), so they are NOT asserted present here.
    IF to_regclass('public.return_window') IS NULL THEN
        RAISE EXCEPTION 'return_window was dropped — it is kept in sym';
    END IF;
END $$;

ROLLBACK;
