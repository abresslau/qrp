-- Verify equity:equity_schema on pg

BEGIN;

SELECT 1/count(*) FROM pg_proc WHERE proname = 'set_updated_at';
SELECT 1/count(*) FROM pg_proc WHERE proname = 'product' AND prokind = 'a';
SELECT composite_figi, session_date, close, currency_code FROM public.prices_raw WHERE false;
SELECT composite_figi, ex_date, action_type, value FROM public.corporate_actions WHERE false;
SELECT composite_figi, session_date FROM public.price_gaps WHERE false;
SELECT composite_figi, session_date, flag_type, reviewed FROM public.prices_review WHERE false;
SELECT composite_figi, source, cursor_date, status FROM public.pipeline_backfill_progress WHERE false;
SELECT run_id, mode, status FROM public.pipeline_run_log WHERE false;
SELECT composite_figi, window_id, as_of_date, pr, tr, input_hash, gated FROM public.fact_returns WHERE false;
SELECT composite_figi, as_of_date, high_52w, low_52w FROM public.fact_price_extremes WHERE false;
SELECT code, name FROM public.currency WHERE false;
SELECT window_id, code, kind FROM public.return_window WHERE false;
SELECT composite_figi, session_date, adj_close, split_factor FROM public.v_prices_adjusted WHERE false;

COMMIT;
