-- Verify sym:price_storage on pg

BEGIN;

-- retrieved_at intentionally not selected: it is dropped by a later change
-- (prices_raw_drop_retrieved_at), and this verify must survive a full re-verify.
SELECT composite_figi, session_date, open, high, low, close, volume,
       currency_code, source, created_at, updated_at
  FROM prices_raw WHERE FALSE;

SELECT composite_figi, ex_date, action_type, value, currency_code, source
  FROM corporate_actions WHERE FALSE;

SELECT composite_figi, source, cursor_date, status, detail
  FROM pipeline_backfill_progress WHERE FALSE;

SELECT composite_figi, session_date, source, detected_at
  FROM price_gaps WHERE FALSE;

-- prices_raw must NOT carry a vendor adjusted-close column (FR-5/AR-7).
SELECT 1 / (CASE WHEN NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'prices_raw'
       AND column_name IN ('adjusted_close', 'adj_close')
) THEN 1 ELSE 0 END);

ROLLBACK;
