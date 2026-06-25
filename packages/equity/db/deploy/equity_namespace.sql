-- Deploy equity:equity_namespace to pg
-- requires: seed_reference

-- Move every equity object out of `public` into a dedicated `equity` schema — matching the
-- per-package named-schema convention (fx.*, universe.*). The objects were created in public by
-- equity_schema/seed_reference; ALTER ... SET SCHEMA relocates them in place (catalog-only — no data
-- copy; indexes/constraints/triggers/sequences follow their table, the view follows its tables by
-- dependency). A DB-level search_path makes bare table names (the engine + every consumer read
-- `prices_raw`/`fact_returns`/… unqualified) resolve to the equity schema on EVERY connection,
-- however it was opened — more robust than a per-connection pin.

BEGIN;

CREATE SCHEMA IF NOT EXISTS equity;

ALTER TABLE     public.prices_raw                 SET SCHEMA equity;
ALTER TABLE     public.corporate_actions          SET SCHEMA equity;
ALTER TABLE     public.price_gaps                 SET SCHEMA equity;
ALTER TABLE     public.prices_review              SET SCHEMA equity;
ALTER TABLE     public.pipeline_backfill_progress SET SCHEMA equity;
ALTER TABLE     public.pipeline_run_log           SET SCHEMA equity;
ALTER TABLE     public.fact_returns               SET SCHEMA equity;
ALTER TABLE     public.fact_price_extremes        SET SCHEMA equity;
ALTER TABLE     public.currency                   SET SCHEMA equity;
ALTER TABLE     public.return_window              SET SCHEMA equity;
ALTER VIEW      public.v_prices_adjusted          SET SCHEMA equity;
ALTER FUNCTION  public.set_updated_at()           SET SCHEMA equity;
ALTER AGGREGATE public.product(numeric)           SET SCHEMA equity;

COMMIT;

-- search_path is a per-database setting that takes effect on subsequent connections (cannot run in
-- the transaction above alongside the moves, but is idempotent + connection-scoped).
ALTER DATABASE equity SET search_path TO equity, public;
