-- Revert indices:indices_schema from pg
-- Drop the indices schema (all objects cascade) + reset the DB search_path.

ALTER DATABASE indices RESET search_path;

BEGIN;

DROP SCHEMA IF EXISTS indices CASCADE;

COMMIT;
