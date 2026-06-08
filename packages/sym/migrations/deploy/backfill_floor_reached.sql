-- Deploy sym:backfill_floor_reached to pg
-- requires: price_storage

BEGIN;

-- Gap-aware backfill needs to know the deepest history floor already requested
-- for a security, not just the latest loaded session (the cursor). Without it, a
-- name first loaded from a late start (e.g. an index member loaded from its
-- membership-join date) looks "complete" via the forward cursor while its history
-- below the earliest stored bar was never fetched. floor_reached records the
-- minimum floor a successful backfill has covered; a backfill skips a name only
-- when floor_reached <= the requested floor AND the cursor is current. NULL means
-- "never backfilled to a known floor" → fetch.
ALTER TABLE pipeline_backfill_progress ADD COLUMN floor_reached DATE;

COMMENT ON COLUMN pipeline_backfill_progress.floor_reached IS 'Deepest history floor a successful backfill has covered (gap-aware backfill). NULL = unknown → fetch.';

COMMIT;
