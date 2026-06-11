-- Verify altdata:generic_series on pg

BEGIN;

SELECT composite_figi, source, metric, ticker, name, detail, unit, frequency
  FROM altdata.series WHERE FALSE;

SELECT composite_figi, source, metric, obs_date, value
  FROM altdata.observation WHERE FALSE;

DO $$
BEGIN
    IF to_regclass('altdata.wiki_map') IS NOT NULL
       OR to_regclass('altdata.pageview') IS NOT NULL THEN
        RAISE EXCEPTION 'legacy wiki tables still present after generic_series';
    END IF;
    -- The observation FK onto series must exist (ON DELETE CASCADE discipline).
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'altdata.observation'::regclass AND contype = 'f'
    ) THEN
        RAISE EXCEPTION 'observation -> series foreign key missing';
    END IF;
END
$$;

ROLLBACK;
