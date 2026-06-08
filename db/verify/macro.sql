-- Verify qrp:macro on pg

BEGIN;

SELECT series_id, source, name, geo, unit, frequency, updated_at
  FROM macro.series WHERE FALSE;
SELECT series_id, obs_date, value FROM macro.observation WHERE FALSE;

ROLLBACK;
