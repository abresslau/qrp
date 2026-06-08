-- Deploy sym:prices_raw_drop_retrieved_at to pg
-- requires: price_storage

-- retrieved_at was redundant with created_at for live ingestion: a row is
-- written immediately after it is fetched, so created_at already records the
-- vintage and updated_at (bumped by the weekly sweep's re-fetch) records the
-- last refresh. Drop it; the OhlcvResult still carries retrieved_at in-memory.
BEGIN;

ALTER TABLE prices_raw DROP COLUMN retrieved_at;

COMMIT;
