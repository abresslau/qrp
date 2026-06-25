-- Revert equity:equity_schema from pg

BEGIN;

DROP VIEW IF EXISTS public.v_prices_adjusted;
DROP TABLE IF EXISTS public.fact_price_extremes;
DROP TABLE IF EXISTS public.fact_returns;
DROP TABLE IF EXISTS public.pipeline_run_log;
DROP TABLE IF EXISTS public.pipeline_backfill_progress;
DROP TABLE IF EXISTS public.prices_review;
DROP TABLE IF EXISTS public.price_gaps;
DROP TABLE IF EXISTS public.corporate_actions;
DROP TABLE IF EXISTS public.prices_raw;
DROP TABLE IF EXISTS public.return_window;
DROP TABLE IF EXISTS public.currency;
DROP AGGREGATE IF EXISTS public.product(numeric);
DROP FUNCTION IF EXISTS public.set_updated_at();

COMMIT;
