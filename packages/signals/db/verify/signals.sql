-- Verify signals:signals on pg

BEGIN;

SELECT factor_key, name, description, direction FROM signals.factor WHERE FALSE;
SELECT universe_id, as_of_date, factor_key, composite_figi, raw, zscore, rank, pctile
  FROM signals.score WHERE FALSE;

ROLLBACK;
