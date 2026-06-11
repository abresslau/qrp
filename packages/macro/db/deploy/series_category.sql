-- Deploy macro:series_category to pg
-- requires: macro

BEGIN;

-- Topic dimension for console sub-navigation (Story C.1): each catalog entry DECLARES its
-- category in the ingest config (like name/unit); the API's categories endpoint reads
-- DISTINCT from this column so the submenu can never drift from the data. Nullable so the
-- column can deploy ahead of the first categorising ingest.
ALTER TABLE macro.series
    ADD COLUMN IF NOT EXISTS category TEXT;

-- Slug shape enforced in the DB, not just the Python ingest guard: these values land
-- verbatim in console URLs, so an out-of-band write must not be able to break links.
-- Added SEPARATELY from the column: if the column ever pre-exists, IF NOT EXISTS would
-- silently skip an inline constraint — the guard must attach either way.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'series_category_is_slug'
           AND conrelid = 'macro.series'::regclass
    ) THEN
        ALTER TABLE macro.series
            ADD CONSTRAINT series_category_is_slug
            CHECK (category IS NULL OR category ~ '^[a-z]+$');
    END IF;
END
$$;

COMMENT ON COLUMN macro.series.category IS
    'Declared topic for console sub-navigation. Canonical set (lower-case URL-safe slugs): '
    'inflation, rates, gdp, employment, debt, population.';

COMMIT;
