-- Verify equity:equity_schema on pg

BEGIN;

SELECT 1/count(*) FROM pg_proc WHERE proname = 'set_updated_at';
SELECT 1/count(*) FROM pg_proc WHERE proname = 'product' AND prokind = 'a';
SELECT composite_figi, session_date, close, currency_code FROM prices_raw WHERE false;
SELECT composite_figi, ex_date, action_type, value FROM corporate_actions WHERE false;
SELECT composite_figi, session_date FROM price_gaps WHERE false;
SELECT composite_figi, session_date, flag_type, reviewed FROM prices_review WHERE false;
SELECT composite_figi, source, cursor_date, status FROM pipeline_backfill_progress WHERE false;
SELECT run_id, mode, status FROM pipeline_run_log WHERE false;
SELECT composite_figi, window_id, as_of_date, pr, tr, input_hash, gated FROM fact_returns WHERE false;
SELECT composite_figi, as_of_date, high_52w, low_52w FROM fact_price_extremes WHERE false;
SELECT code, name FROM currency WHERE false;
SELECT window_id, code, kind FROM return_window WHERE false;
SELECT composite_figi, session_date, adj_close, split_factor FROM v_prices_adjusted WHERE false;

COMMIT;
