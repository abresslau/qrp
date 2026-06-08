-- Verify qrp:signal on pg

BEGIN;

SELECT factor_key, name, description, direction FROM signal.factor WHERE FALSE;
SELECT universe_id, as_of_date, factor_key, composite_figi, raw, zscore, rank, pctile
  FROM signal.score WHERE FALSE;

ROLLBACK;
