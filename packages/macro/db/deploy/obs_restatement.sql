-- Deploy macro:obs_restatement to pg
-- requires: macro

BEGIN;

-- Restatement visibility (chunk-1 ledger): observations carried `source` but no way to tell
-- a vendor restatement from a first load. `last_changed_at` is stamped on insert and ONLY
-- re-stamped when an ingest CHANGES the stored value — an equal-value re-ingest must not
-- touch it (the ingest upsert enforces this with a conditional DO UPDATE).
ALTER TABLE macro.observation
    ADD COLUMN IF NOT EXISTS last_changed_at TIMESTAMPTZ NOT NULL DEFAULT now();

COMMENT ON COLUMN macro.observation.last_changed_at IS
    'Insert time, re-stamped only when an ingest changes the value (restatement marker). '
    'Rows predating this column carry the migration deploy time (backfill artifact), not '
    'their insert time. NOT a release/vintage date — point-in-time macro needs a revision '
    'table (deferred).';

COMMIT;
