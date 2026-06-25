-- Revert equity:equity_namespace from pg
-- Move the objects back to public + drop the equity schema + reset the DB search_path.

ALTER DATABASE equity RESET search_path;

BEGIN;

ALTER TABLE     equity.prices_raw                 SET SCHEMA public;
ALTER TABLE     equity.corporate_actions          SET SCHEMA public;
ALTER TABLE     equity.price_gaps                 SET SCHEMA public;
ALTER TABLE     equity.prices_review              SET SCHEMA public;
ALTER TABLE     equity.pipeline_backfill_progress SET SCHEMA public;
ALTER TABLE     equity.pipeline_run_log           SET SCHEMA public;
ALTER TABLE     equity.fact_returns               SET SCHEMA public;
ALTER TABLE     equity.fact_price_extremes        SET SCHEMA public;
ALTER TABLE     equity.currency                   SET SCHEMA public;
ALTER TABLE     equity.return_window              SET SCHEMA public;
ALTER VIEW      equity.v_prices_adjusted          SET SCHEMA public;
ALTER FUNCTION  equity.set_updated_at()           SET SCHEMA public;
ALTER AGGREGATE equity.product(numeric)           SET SCHEMA public;

DROP SCHEMA IF EXISTS equity;

COMMIT;
