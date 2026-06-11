-- Revert macro:series_category from pg

BEGIN;

ALTER TABLE macro.series DROP COLUMN IF EXISTS category;

COMMIT;
