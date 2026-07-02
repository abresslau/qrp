-- Revert equity:fact_asset_metrics from pg

BEGIN;

DROP TABLE IF EXISTS equity.fact_asset_metrics;

COMMIT;
