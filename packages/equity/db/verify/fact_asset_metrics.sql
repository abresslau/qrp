-- Verify equity:fact_asset_metrics on pg

BEGIN;

SELECT composite_figi, window_id, as_of_date, vol_pr, vol_tr, sharpe_pr, sharpe_tr,
       n_obs, input_hash, gated
  FROM equity.fact_asset_metrics WHERE false;

-- PK + window FK present
SELECT 1/count(*) FROM pg_constraint WHERE conname = 'fact_asset_metrics_pk';
SELECT 1/count(*) FROM pg_constraint WHERE conname = 'fact_asset_metrics_window_fk';
-- published (not-gated) partial index present
SELECT 1/count(*) FROM pg_indexes WHERE indexname = 'idx_fact_asset_metrics_published';

COMMIT;
